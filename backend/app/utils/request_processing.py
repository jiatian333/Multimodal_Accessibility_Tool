"""
High-Level Request Processing Logic for Location and Travel Resolution

This module provides higher-order utilities to process travel-related requests 
in a multimodal mobility context. It acts as an orchestration layer between 
core spatial logic (e.g., R-tree, walking graphs) and external API calls 
(e.g., OJP).

Responsibilities:
-----------------
- Resolve candidate destinations (POIs, stops, rentals) using either:
    - Local spatial indices (R-tree)
    - External OJP API (fallback)
- Route trip planning requests through `process_trip_request` (from ojp_helpers)
- Handle pre- and post-processing (e.g., polygon filtering, rental edge logic)

Key Functions:
--------------
- `process_location_request(...)`: Retrieves destinations via R-tree or OJP.
- `process_and_get_travel_time(...)`: Computes travel duration (via OJP or walking).

Raises:
-------
- `RateLimitExceededError`: If OJP returns HTTP 429 during request processing.

Typical Use:
------------
Used by:
- `network_travel_times(...)` in `app.processing.travel_times.travel_computation.py`
- `point_travel_times(...)` in `app.processing.travel_times.travel_computation.py`

Imports:
--------
- Spatial: R-tree, walking graphs, polygon filters
- Request/response building: app.requests.*
- OJP logic: imported from `app.utils.ojp_helpers`
"""



import logging
from typing import Tuple, List, Optional, Dict

import networkx as nx
import pandas as pd
from pyproj import Transformer
from rtree.index import Index
from shapely.geometry import Point, Polygon
from shapely.ops import transform

from app.core.config import (
    USE_RTREE_SEARCH, WALKING_NETWORK, TransportModes
)
from app.core.data_types import TravelData
from app.requests.parse_response import (
    parse_trip_response, decode_duration
)
from app.utils.filtering_locations import (
    polygon_filter, filter_destinations
)
from app.utils.ojp_helpers import (
    query_ojp_travel_time, location_ojp
)
from app.utils.rtree_structure import find_nearest
from app.utils.routing import estimated_walking_time

logger = logging.getLogger(__name__)

async def process_location_request(
    random_point: Point,
    radius: int,
    restriction_type: str,
    poi_filter: str,
    polygon: Polygon,
    rtree_indices: Dict[str, Index],
    mode: TransportModes,
    G: nx.MultiDiGraph,
    travel_data: TravelData,
    timestamp: str,
    num_results: int = 1,
    rental: bool = False,
    include_pt_modes: bool = True,
    public_transport_modes: Optional[pd.DataFrame] = None
) -> Tuple[Optional[List[Point]], Optional[List[List[str]]], Optional[Point], Optional[float]]:
    """
    Main logic for retrieving valid destinations either from R-tree or OJP API.

    Args:
        random_point (Point): Origin point.
        radius (int): Search radius in meters.
        restriction_type (str): Type of restriction (e.g., 'stop').
        poi_filter (str): Concrete POI filter.
        polygon (Polygon): Boundary to filter destinations inside.
        rtree_indices (Dict[str, Index]): Dictionary of R-tree spatial indices.
        mode (TransportModes): Current transport mode.
        G (nx.MultiDiGraph): Walking graph.
        travel_data (TravelData): Cached travel time info.
        timestamp (str): Time of request (ISO 8601 format).
        num_results (int, optional): Number of nearest results. Default is 1.
        rental (bool, optional): Enable additional rental filtering. Default is False.
        include_pt_modes (bool, optional): Whether to request PT modes. Default is True.
        public_transport_modes (pd.DataFrame, optional): DataFrame with public transport mode metadata.

    Returns:
        Tuple[List[Point], List[List[str]], Optional[Point], Optional[float]]:
            Destinations, modes, and optionally the nearest match and the walking travel time.
    """
    destinations: List[Point] = []
    modes: List[List[str]] = []
    nearest: Optional[Point] = None
    walking_travel_time: Optional[float] = None

    if USE_RTREE_SEARCH:
        search_type = 'public-transport' if restriction_type == 'stop' else mode
        nearest_stations = find_nearest(
            rtree_indices, random_point.x, random_point.y, 
            search_type, num_results=num_results
        )
        destinations = [Point(obj.bbox[:2]) for obj in nearest_stations]

        for obj in nearest_stations:
            match = public_transport_modes[
                (public_transport_modes['longitude'] == obj.bbox[0]) &
                (public_transport_modes['latitude'] == obj.bbox[1])
            ]
            modes.append(match['transport_modes'].values[0].split('|') if not match.empty else [])

    destinations, modes = polygon_filter(polygon, modes, destinations)

    if not destinations:
        logger.debug(f"No R-tree matches. Falling back to OJP request for mode='{mode}'")
        destinations, modes = await location_ojp(
            random_point, num_results, include_pt_modes, radius, restriction_type, poi_filter, timestamp
        )
        if not destinations:
            return [], [], None, None

    destinations, modes = polygon_filter(polygon, modes, destinations)
    logger.debug(f"{len(destinations)} destinations remain after polygon filtering.")

    if restriction_type == 'stop' and rental:
        logger.debug(f"Filtering rental destinations with mode='{mode}' from {len(destinations)} candidates.")
        best_desination, best_nearest, walking_travel_time = await filter_destinations(
            random_point, destinations, modes, rtree_indices, G, travel_data, mode, timestamp
        )
        return ([best_desination], 
                [modes[destinations.index(best_desination)]], 
                best_nearest, walking_travel_time
        )

    return destinations, modes, nearest, walking_travel_time

async def process_and_get_travel_time(
    start: Point,
    end: Point,
    mode_xml: str,
    mode: TransportModes,
    G: nx.MultiDiGraph, 
    arr: str,
    timestamp: str, 
    transformer: Transformer
) -> Optional[float]:
    """
    Computes the travel duration between two points using either the local walking network or OJP API.

    For walk trips and short distances, local heuristics or walking graph estimates are used.
    For all other modes, sends a request to OJP and extracts the travel time from the response.

    Args:
        start (Point): Origin location in EPSG:4326.
        end (Point): Destination location in EPSG:4326.
        mode_xml (str): XML representation of travel mode.
        mode (TransportModes): Travel mode.
        G (nx.MultiDiGraph): Network graph (used for walking).
        arr (str): Time of arrival (ISO 8601 format).
        timestamp (str): Time of request (ISO 8601 format).
        transformer (Transformer): Transforms data from initial crs (EPSG:4326) to target crs (EPSG:2056).

    Returns:
        Optional[float]: Travel duration in minutes, or None if not found.
    """
    
    if start.equals(end):
        logger.debug("Start and end points are identical. Returning 0.0 min.")
        return 0.0
    
    projected_distance = transform(transformer.transform, start).distance(
        transform(transformer.transform, end)
    )
    
    if projected_distance < 30:
        logger.debug(f"Start and end are very close ({projected_distance:.2f} m). Returning 1.0 min.")
        return 1.0
    
    if WALKING_NETWORK and mode == "walk":
        logger.debug("Using walking network to estimate travel time.")
        return estimated_walking_time(start, end, G)
    
    duration = await query_ojp_travel_time(
        start,
        end,
        mode,
        mode_xml,
        timestamp,
        arr,
        parse_fn=lambda xml, m: decode_duration(j) if (j := parse_trip_response(xml, m)) else []
    )

    return duration