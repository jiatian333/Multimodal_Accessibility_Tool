"""
Destination Filtering and Ranking Utilities

This module handles candidate filtering and ranking for destination access,
using a combination of spatial indexing, graph routing, and multimodal scoring.

Core Logic
----------
- Cached nearest lookup (from rental storage).
- Fast R-tree based nearest search using spatial index.
- Graph-based weighted shortest path scoring.
- Fallback to Open Journey Planner (OJP) for last-resort resolution.

Functions
---------
- filter_destinations(...): Filters and ranks destinations using caching, R-tree, and OJP fallback.
- polygon_filter(...): Clips destination points and mode lists to fall within a polygon.
- _nearest_from_rtree(...): Retrieves nearby candidates from an R-tree spatial index.
- _nearest_from_ojp(...): Sends a fallback OJP API request to retrieve nearby POIs.

Returns
-------
Selected destinations and optionally walking distances based on priority and access cost.
"""


import logging
from typing import Tuple, List, Optional, Dict

import networkx as nx
from shapely.geometry import Point, Polygon
from rtree.index import Index

from app.core.config import (
    USE_RTREE_SEARCH, TransportModes
)
from app.core.data_types import TravelData
from app.data.rental_storage import get_stored_closest_rental
from app.utils.candidate_selection import evaluate_best_candidate
from app.utils.mode_utils import select_parameters
from app.utils.ojp_helpers import location_ojp
from app.utils.rtree_structure import find_nearest

logger = logging.getLogger(__name__)

def _nearest_from_rtree(
    point: Point,
    rtree_indices: Dict[str, Index],
    mode: TransportModes,
    num_results: int = 2
) -> List[Point]:
    """
    Retrieves nearby candidate points from the R-tree spatial index using Euclidean proximity.

    Args:
        point (Point): Origin location to search from.
        rtree_indices (Dict[str, Index]): R-tree spatial indices per transport mode.
        mode (TransportModes): Transport mode for which the spatial index is queried.
        num_results (int): Number of nearest candidates to return (default is 2).

    Returns:
        List[Point]: Candidate destination points ordered by spatial proximity.
    """
    results = find_nearest(rtree_indices, point.x, point.y, mode, num_results=num_results)
    return [Point(res.bbox[:2]) for res in results] if results else []

async def _nearest_from_ojp(
    point: Point,
    radius: int,
    restriction_type: str,
    poi_filter: str,
    timestamp: str
) -> List[Point]:
    """
    Uses the OJP API to retrieve valid destination points near the given origin.

    Args:
        point (Point): The origin location to search from.
        radius (int): Search radius in meters.
        restriction_type (str): Restriction type ('stop' or 'poi').
        poi_filter (str): POI filter string used in OJP query.
        timestamp (str): Current time of request (ISO 8601 format).

    Returns:
        List[Point]: List of destination points (possibly empty).
    """
    nearest_list, _ = await location_ojp(
        point, num_results=2, include_pt_modes=False,
        radius=radius, restriction_type=restriction_type,
        poi_filter=poi_filter, timestamp=timestamp
    )
    return nearest_list if nearest_list else []

async def filter_destinations(
    origin: Point,
    destinations: List[Point],
    public_modes: List[List[str]],
    rtree_indices: Dict[str, Index],
    G: nx.MultiDiGraph,
    travel_data: TravelData,
    mode: TransportModes, 
    timestamp: str
) -> Tuple[Optional[Point], Optional[Point], Optional[float]]:
    """
    Filters rental destinations based on distance and transport mode priorities
    by balancing walking distance and travel distance using the corresponding mode.

    This function  uses the R-tree spatial index or falls back to an OJP request to 
    find the nearest candidates. Distance is evaluated using shortest-path distance 
    and weighted by mode importance.

    Args:
        origin (Point): Starting point for travel.
        destinations (List[Point]): Candidate destination points.
        public_modes (List[List[str]]): Available transport modes for each destination.
        rtree_indices (Dict[str, Index]): Prebuilt R-tree spatial indices per mode.
        G (nx.MultiDiGraph): Walking graph for for shortest-path calculations.
        travel_data (TravelData): Dictionary of stored travel time information.
        mode (TransportModes): Transport mode (e.g., walk, bicycle_rental).
        timestamp (str): Timestamp string in ISO-8601 format (for OJP API fallback).

    Returns:
        Tuple[Optional[Point], Optional[Point], Optional[float]]: 
            Best (destination, nearest match, walking time or None).
    """
        
    candidates = list(zip(destinations, public_modes))
    
    if USE_RTREE_SEARCH:
        best_destination, best_nearest, best_walking = await evaluate_best_candidate(
            origin, candidates, 
            lambda point: get_stored_closest_rental(travel_data, mode, point, point_isochrones=False),
            lambda point: _nearest_from_rtree(point, rtree_indices, mode, num_results=2),
            mode, G
        )
        if best_destination:
            return best_destination, best_nearest, best_walking
        
    logger.debug("Fallback to OJP-based location search because R-tree failed or returned no results.")
    radius, restriction_type, poi_filter = select_parameters(mode, rental=True)
    
    async def nearest_from_ojp_wrapper(point: Point) -> List[Point]:
        """
        Lightweight wrapper around `_nearest_from_ojp` for compatibility with async batch processing.

        Args:
            point (Point): The origin coordinate to search nearby destinations from.

        Returns:
            List[Point]: List of nearby POIs (e.g., rental stations or stops) returned from the OJP API.
        """
        return await _nearest_from_ojp(point, radius, restriction_type, poi_filter, timestamp)
    
    best_destination, best_nearest, best_walking = await evaluate_best_candidate(
        origin, candidates, 
        lambda point: get_stored_closest_rental(travel_data, mode, point, point_isochrones=False),
        nearest_from_ojp_wrapper,
        mode, G
    )

    return best_destination, best_nearest, best_walking

def polygon_filter(
    polygon: Polygon,
    modes: List[List[str]],
    destinations: List[Point]
) -> Tuple[List[Point], List[List[str]]]:
    """
    Filters destinations and modes to include only those inside a polygon.

    Args:
        polygon (Polygon): Area boundary to filter within.
        modes (List[List[str]]): Modes for each destination.
        destinations (List[Point]): List of candidate destination points.

    Returns:
        Tuple[List[Point], List[List[str]]]: Filtered destinations and modes within the polygon.
    """
    filtered = [(dest, modes[i]) for i, dest in enumerate(destinations) if polygon.contains(dest)]
    return tuple(map(list, zip(*filtered))) if filtered else ([], [])