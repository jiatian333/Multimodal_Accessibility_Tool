"""
Spatial Routing and Nearest Station Utilities

This module provides graph-based routing and R-tree-based spatial filtering to support
efficient nearest station selection, parking lookup, and walking-time estimation.

Core Features
-------------
- R-tree spatial nearest lookup with polygon filtering
- Walking network-based shortest-path calculations using OSMnx
- Mode-aware weighted candidate selection
- Caching integration for optimized performance

Functions
---------
- estimated_walking_time(...): Calculates walking time between two points using shortest-path.
- find_closest_parking(...): Finds closest reachable point from an origin based on actual walking distance.
- find_valid_nearest_station(...): Selects the best destination point based on weighted distance, with caching support.
- _nearest_from_rtree_filtered(...): R-tree nearest neighbor query with polygon filtering.

Returns
-------
Filtered or ranked destination points, optionally with walking time.
"""


import logging
import math
from typing import Tuple, List, Optional, Dict

import networkx as nx
import osmnx as ox
from rtree.index import Index
from shapely.geometry import Point, Polygon

from app.core.config import WALKING_SPEED, TransportModes
from app.core.data_types import TravelData
from app.data.parking_storage import get_stored_parking_info
from app.utils.candidate_selection import evaluate_best_candidate
from app.utils.rtree_structure import find_nearest

logger = logging.getLogger(__name__)

def estimated_walking_time(
    point1: Point,
    point2: Point,
    G: nx.MultiDiGraph
) -> Optional[int]:
    """
    Estimate walking time (in minutes) using shortest path on a walking network.

    Args:
        point1 (Point): Start location.
        point2 (Point): End location.
        G (nx.MultiDiGraph): Preloaded walking network graph.

    Returns:
        Optional[int]: Walking time in whole minutes, or None if invalid. 
    """
    
    try:
        orig_node = ox.distance.nearest_nodes(G, point1.x, point1.y)
        dest_node = ox.distance.nearest_nodes(G, point2.x, point2.y)
        length = nx.shortest_path_length(G, orig_node, dest_node, weight='length')
        walking_time = math.ceil(length / WALKING_SPEED / 60)
        logger.debug(f"Shortest walking time: {walking_time:.2f} min from start={point1} to end={point2}.")
        return walking_time
    except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
        logger.error(f"No walking path found: {e}")
        return None

def find_closest_parking(
    idx: Dict[str, Index],
    lon: float,
    lat: float,
    G: nx.MultiDiGraph,
    mode: TransportModes,
    polygon: Polygon
) -> Optional[Point]:
    """
    Finds the closest parking candidate using walking path distance, not mode weighting.
    Mainly used for point isochrones, this function finds the spatially reachable parking facility with the minimal network distance.

    Args:
        idx (Dict[str, Index]): R-tree spatial index.
        lon (float): Longitude of the origin point.
        lat (float): Latitude of the origin point.
        G (nx.MultiDiGraph): Walking network graph.
        mode (TransportModes): Transport mode key for R-tree lookup.
        polygon (Polygon): Valid spatial boundary to constrain results.

    Returns:
        Optional[Point]: The closest reachable parking point.
    """
    parking_facilities = find_nearest(idx, lon, lat, mode, num_results=2)
    orig_node = ox.distance.nearest_nodes(G, lon, lat)

    nearest_parking: Optional[Point] = None
    min_distance = float('inf')

    for parking in parking_facilities:
        p_lon, p_lat = parking.bbox[:2]
        candidate = Point(p_lon, p_lat)

        if not polygon.contains(candidate):
            continue

        try:
            parking_node = ox.distance.nearest_nodes(G, p_lon, p_lat)
            distance = nx.shortest_path_length(G, orig_node, parking_node, weight='length')
        except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
            logger.warning(f'Invalid distance returned from walking network. Skipping this parking location: {e}')
            continue

        if distance < min_distance:
            min_distance = distance
            nearest_parking = candidate

        if min_distance == 0:
            break
    logger.debug(f"Successfully determined nearest parking={nearest_parking} from destination={Point(lon, lat)} for mode={mode}.")
    return nearest_parking

def _nearest_from_rtree_filtered(
    point: Point,
    rtree_indices: Dict[str, Index],
    mode: TransportModes,
    polygon: Polygon,
    num_results: int = 2
) -> List[Point]:
    """
    Returns R-tree nearest candidates filtered by a spatial boundary.

    This function queries the spatial index for nearby destinations, then
    applies a polygon constraint to filter out those outside the valid area.

    Args:
        point (Point): Origin point for the spatial search.
        rtree_indices (Dict[str, Index]): Dictionary of spatial indices per mode.
        mode (TransportModes): Mode key to access the corresponding index.
        polygon (Polygon): Boundary polygon for filtering.
        num_results (int): Number of nearest candidates to return. Default = 2.

    Returns:
        List[Point]: List of valid destination points within the polygon.
    """
    results = find_nearest(rtree_indices, point.x, point.y, mode, num_results=num_results)
    return [
        candidate for candidate in (Point(r.bbox[:2]) for r in results)
        if polygon.contains(candidate)
    ]


async def find_valid_nearest_station(
    origin: Point, 
    idx: Dict[str, Index],
    destinations: List[Point],
    mode: TransportModes,
    travel_data: TravelData,
    G: nx.MultiDiGraph,
    public_transport_modes: List[List[str]],
    polygon: Polygon
) -> Tuple[Optional[Point], Optional[Point], Optional[float]]:
    """
    Finds the best parking station candidate for private transport modes.

    Selects the nearest valid station based on a weighted scoring of:
    - Walking distance from destination to parking location.
    - Mode travel distance from origin to parking location.

    If cached results exist, they are preferred. Otherwise, a spatial nearest-neighbor search is used.

    Args:
        origin (Point): Starting point.
        idx (Dict[str, Index]): R-tree indices for fast spatial lookup.
        destinations (List[Point]): Candidate station points.
        mode (TransportModes): Mode for which to find the nearest station.
        travel_data (TravelData): Cached travel times and station results.
        G (nx.MultiDiGraph): Walking network graph.
        public_transport_modes (List[List[str]]): Available transport modes per destination.
        polygon (Polygon): Boundary to filter valid stations.

    Returns:
        Tuple[Optional[Point], Optional[Point], Optional[float]]:
            (Selected destination, Nearest match, Walking time if available)
    """
        
    candidates = list(zip(destinations, public_transport_modes))
    nearest_func = lambda point: _nearest_from_rtree_filtered(point, idx, mode, polygon, num_results=2)
    stored_func = lambda point: get_stored_parking_info(travel_data, point, mode, point_isochrones=False)
    
    best_destination, best_nearest, best_walking = await evaluate_best_candidate(origin, candidates, stored_func, nearest_func, mode, G)
    return best_destination, best_nearest, best_walking