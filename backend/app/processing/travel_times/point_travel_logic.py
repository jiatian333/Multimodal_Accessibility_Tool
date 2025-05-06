"""
Routing Helper Functions for Point-Based Isochrones

This module provides reusable helper logic specifically tailored for calculating 
isochrones from a single origin point to many destination points (point-based strategy).

Responsibilities:
-----------------
- Determine origin access point (e.g., rental station, parking).
- Resolve nearest station at each destination for rental modes.
- Aggregate walk time + mode time across point pairs.
- Interface with TravelData for caching travel time results.

Key Functions:
--------------
- `should_skip_radial_point(...)`: Checks if a point was already processed.
- `resolve_origin_station(...)`: Returns walk access point and time for center point.
- `resolve_destination_station(...)`: Returns access station near each destination point.
- `compute_total_point_time(...)`: Aggregates time from origin → destination with walking.

Requirements:
-------------
- Called internally by `point_travel_times(...)` in `travel_computation.py`.
- Requires R-tree indices, walking graph, and pre-configured mode logic.

Usage:
------
    from app.processing.travel_times.point_travel_logic import (
        should_skip_radial_point,
        resolve_origin_station,
        resolve_destination_station,
        compute_total_point_time
    )

Logging:
--------
- Logs errors in walk routing, fallback queries, and travel failures.
- Traceable warnings for each individual point skip.
"""

import logging
import math
from typing import Dict, Optional, Tuple

import networkx as nx
import pandas as pd
from pyproj import Transformer
from rtree.index import Index
from shapely.geometry import Point, Polygon

from app.core.config import WALKING_SPEED, TransportModes
from app.core.data_types import TravelData, TravelDataMode
from app.data.distance_storage import distance_cache
from app.data.parking_storage import (
    get_stored_parking_info, store_parking
)
from app.data.rental_storage import (
    get_stored_closest_rental,
    store_closest_rental
)
from app.utils.mode_utils import mode_selection
from app.utils.request_processing import (
    process_and_get_travel_time,
    process_location_request
)
from app.utils.routing import find_closest_parking


logger = logging.getLogger(__name__)

def should_skip_radial_point(
    point: Point, 
    mode_data: TravelDataMode, 
    center: Point
) -> bool:
    """
    Checks if a radial point has already been processed and stored in travel_data using the center point.

    Skips redundant computation by detecting previously cached travel times.

    Args:
        point (Point): The radial point to check. 
        mode_data (TravelDataMode): The cached data structure for a specific mode.
        center (Point): Center of the point isochrones.

    Returns:
        bool: True if the point is already processed, False otherwise.
    """
    logger.debug('----------------------------------------------------------')
    if center in mode_data["point_isochrones"] and point in mode_data["point_isochrones"][center]["points"]:
        logger.info(f"Skipping radial point: {point}, already processed for center {center}.")
        return True
    return False

async def resolve_origin_station(
    center: Point,
    mode: TransportModes,
    rental: bool,
    travel_data: TravelData,
    idx: Dict[str, Index],
    G: nx.MultiDiGraph,
    polygon: Polygon,
    timestamp: str,
    transformer: Transformer,
    arr: str,
    public_transport_modes: pd.DataFrame,
    radius: int,
    restriction_type: str,
    poi_filter: str
) -> Tuple[Optional[Point], float, TravelData]:
    """
    Resolves the access station (rental or parking) and walking time from the center origin.

    Checks cached results if available, otherwise:
    - Uses `process_location_request` to find nearby rental stations.
    - Uses `find_closest_parking` for non-rental modes.

    Args:
        center (Point): The origin point in EPSG:4326.
        mode (TransportModes): The current transport mode (e.g. bicycle_rental).
        rental (bool): Whether the mode uses rental access logic.
        travel_data (TravelData): The travel time cache.
        idx (Dict[str, Index]): R-tree indices for quick spatial access.
        G (nx.MultiDiGraph): Walking graph for path computations.
        polygon (Polygon): Valid spatial boundary (city limits, etc.).
        timestamp (str): Current processing timestamp.
        transformer (Transformer): Coordinate system transformer.
        arr (str): Arrival time in ISO-8601 format.
        public_transport_modes (pd.DataFrame): Metadata about PT modes and availability.
        radius (int): Search radius in meters.
        restriction_type (str): Restriction type for POI/rental logic.
        poi_filter (str): OJP-compatible POI filter string.

    Returns:
        Tuple[Optional[Point], float, TravelData]:
            - The resolved access point (rental station or parking; center for walk)
            - Walking time from center to the access point
            - Possibly updated travel_data cache
    """
    if mode != 'walk':
        if rental:
            nearest, travel_time_start = get_stored_closest_rental(
                travel_data, mode, center, point_isochrones=True
            )
        else:
            nearest, travel_time_start = get_stored_parking_info(
                travel_data, center, mode, point_isochrones=True
            )
        
        if not nearest:
            cached = distance_cache.get_cached_nearest(center, mode)
            if cached:
                nearest, walk_length = cached
                travel_time_start = math.ceil(walk_length / WALKING_SPEED / 60)
                logger.debug(f"Using cached nearest for {center}: {nearest}")

        if not nearest:
            if rental:
                nearest, _, _, _ = await process_location_request(
                    center, radius, restriction_type, poi_filter,
                    polygon, idx, mode, G, travel_data, timestamp, 
                    num_results=1, rental=rental, include_pt_modes=False,
                    public_transport_modes=public_transport_modes
                )
                if not nearest:
                    logger.error(f'No valid rental station found near origin {center}. Skipping isochrone.')
                    return None, 0.0, travel_data
                nearest = nearest[0]
            else:
                nearest = find_closest_parking(idx, center.x, center.y, G, mode, polygon)

            if not nearest:
                logger.error(f'No valid station found near origin {center}. Skipping isochrone.')
                return None, 0.0, travel_data
            
            travel_time_start = await process_and_get_travel_time(
                center, nearest, mode_selection('walk'), 'walk', G, arr, timestamp, transformer
            )
            if travel_time_start is None:
                logger.error(f'Failed to compute walking time from origin {center} to nearest station. Skipping isochrone.')
                return None, 0.0, travel_data

            if rental:
                await store_closest_rental(
                    travel_data, mode, center, nearest, travel_time_start, point_isochrones=True
                )
            else:
                await store_parking(
                    mode, center, nearest, travel_data, travel_time_start, point_isochrones=True
                )
        return nearest, travel_time_start, travel_data
    return center, 0.0, travel_data
    

async def resolve_destination_station(
    radial_point: Point,
    mode: TransportModes,
    rental: bool,
    travel_data: TravelData,
    idx: Dict[str, Index],
    G: nx.MultiDiGraph,
    polygon: Polygon,
    timestamp: str,
    transformer: Transformer,
    arr: str,
    public_transport_modes: pd.DataFrame,
    radius: int,
    restriction_type: str,
    poi_filter: str
) -> Tuple[Optional[Point], Optional[float]]:
    """
    Resolves the nearest valid station (rental access point) for the destination side.
    
    Only applies to rental-based modes. Uses spatial index + routing to evaluate:
    - Station near destination
    - Walking time from radial point to resolved station

    Args:
        radial_point (Point): The destination point to resolve.
        mode (TransportModes): Travel mode in use.
        rental (bool): Whether this mode uses rental logic.
        travel_data (TravelData): Cache structure with known rentals and times.
        idx (Dict[str, Index]): Spatial index (R-tree) for the relevant transport mode.
        G (nx.MultiDiGraph): Walking graph.
        polygon (Polygon): Spatial filter area.
        timestamp (str): Time of the query.
        transformer (Transformer): Coordinate transformer for routing.
        arr (str): Desired arrival time in ISO format.
        public_transport_modes (pd.DataFrame): Public transport metadata.
        radius (int): Search radius in meters.
        restriction_type (str): OJP API restriction type.
        poi_filter (str): Filter string for POI types.

    Returns:
        Tuple[Optional[Point], Optional[float]]:
            - The resolved end station near the radial point.
            - The walking time to that station, or None if not available.
    """
    nearest_end, _, _, _ = await process_location_request(
        radial_point, radius, restriction_type, poi_filter,
        polygon, idx, mode, G, travel_data, timestamp, 
        num_results=1, rental=rental, include_pt_modes=False,
        public_transport_modes=public_transport_modes
    )
    if not nearest_end:
        logger.warning(f'No valid rental station found near endpoint {radial_point}. Skipping.')
        return None, None

    nearest_end = nearest_end[0]
    travel_time_end = await process_and_get_travel_time(
        radial_point, nearest_end, mode_selection('walk'), 'walk', G, arr, timestamp, transformer
    )
    if travel_time_end is None:
        logger.warning(f'Failed to compute walking time to rental station at destination {radial_point}. Skipping.')
        return None, None

    return nearest_end, travel_time_end

async def compute_total_point_time(
    start: Point,
    radial_point: Point,
    travel_mode: str,
    mode_xml: str,
    travel_time_start: float,
    travel_time_end: float,
    G: nx.MultiDiGraph,
    arr: str,
    timestamp: str,
    transformer: Transformer
) -> Optional[float]:
    """
    Computes the full travel duration from the origin station to the destination.

    Adds walk time from center to origin station (if applicable),
    main travel segment from origin → destination,
    and walk time from destination station to final radial point.

    Args:
        start (Point): Travel start location (either origin or nearest station).
        radial_point (Point): Travel endpoint (or rental station nearby).
        travel_mode (str): Internal routing label (e.g. 'cycle', 'self-drive-car').
        mode_xml (str): OJP-compatible routing keyword.
        travel_time_start (float): Time from center to start.
        travel_time_end (float): Time from endpoint to POI.
        G (nx.MultiDiGraph): Walking graph used for fallback or walk legs.
        arr (str): Target arrival time.
        timestamp (str): ISO-8601 current time.
        transformer (Transformer): Coordinate projection tool.

    Returns:
        Optional[float]: Total combined time (walk + ride + walk), or None on failure.
    """
    travel_time_mode = await process_and_get_travel_time(
        start, radial_point, mode_xml, travel_mode, G, arr, timestamp, transformer
    )
    if travel_time_mode is None:
        logger.warning(f'Failed to compute main mode travel from {start} to {radial_point}. Skipping.')
        return None
    return travel_time_mode + travel_time_start + travel_time_end