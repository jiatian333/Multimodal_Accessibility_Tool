"""
Candidate Evaluation Utilities

This module provides core logic to evaluate and rank destination candidates
for multimodal transport routing, based on a combination of walking distances,
mode-specific travel distances, and weighting heuristics.

Key Features:
-------------
- Weighted travel distance computation incorporating both walking and ride segments.
- Distance boosting based on mode relevance and availability.
- Caching of shortest paths to reduce redundant computations.
- Limiting evaluation scope with `MAX_DESTINATIONS` to optimize performance.

Main Functions:
---------------
- `evaluate_best_candidate`: Selects the optimal destination+access pair for a given origin.
- `compute_weighted_distance`: Calculates a weighted score combining walk + access mode.
- `compute_mode_distance`: Computes route segment for mode (e.g., bike or car).
- `distance_weights`: Assigns distance boosting weight based on mode relevance.
"""

import logging
import math
from collections.abc import Iterable as IterableABC
from typing import (
    Callable, Iterable, List, 
    Optional, Tuple, Union, Dict
)

import networkx as nx
import osmnx as ox
from shapely.geometry import Point

from app.core.config import (
    TransportModes, 
    USE_MODE_WEIGHTING, 
    WALKING_SPEED, 
    MAX_DESTINATIONS
)
from app.data.distance_storage import distance_cache
from app.utils.mode_utils import params_distance_calculation, get_graph

logger = logging.getLogger(__name__)

def distance_weights(
    transport_modes: List[str],
    walk_distance: float,
    mode_priority: Dict[str, int],
    base_max_distance: float,
    boost_factor: float,
    priority_boost_factor: float,
    weight_factor_base: float
) -> Optional[float]:
    """
    Computes a scaling weight to prioritize destinations with better modal connectivity.

    Enhances distance tolerance using mode priority and diversity.
    Used to scale total travel distance (walk + ride) when computing final weights.

    Args:
        transport_modes (List[str]): Available modes at the candidate location.
        walk_distance (float): Distance from destination to access point (meters).
        mode_priority (Dict[str, int]): Priority scores per transport mode.
        base_max_distance (float): Unweighted maximum threshold for walk segment.
        boost_factor (float): Boost based on number of available modes.
        priority_boost_factor (float): Boost for high-priority modes (e.g., rail).
        weight_factor_base (float): Base multiplier for combined priority.

    Returns:
        Optional[float]: Final weight factor, or None if walk distance exceeds threshold.
    """
    mode_scores = [mode_priority.get(m, 0) for m in transport_modes]
    total_priority_score = sum(mode_scores)
    highest_priority = max(mode_scores, default=0)

    count_boost = boost_factor * (len(transport_modes) - 1)
    priority_boost = priority_boost_factor * highest_priority if highest_priority > 1 else 0

    adjusted_max_distance = (
        base_max_distance * (1 + count_boost + priority_boost)
        if USE_MODE_WEIGHTING else base_max_distance
    )

    if walk_distance >= adjusted_max_distance:
        return None

    weight_factor = (
        1 + weight_factor_base * (total_priority_score + 0.5 * (len(transport_modes) - 1))
        if USE_MODE_WEIGHTING else 1
    )

    return weight_factor

def compute_mode_distance(
    origin: Point, 
    G_mode_canton: nx.MultiDiGraph,
    best_nearest: Point, 
    weight_mode: float,
    walk_length: float,
    weight_factor: float
    ) -> Optional[float]:
    """
    Computes travel distance from the origin to access point using a mode-specific graph.

    Combines this with walk segment and weight factor to generate final weighted score.

    Args:
        origin (Point): Origin coordinate.
        G_mode_canton (nx.MultiDiGraph): Network graph for chosen transport mode.
        best_nearest (Point): Destination-adjacent access point.
        weight_mode (float): Scaling factor for mode contribution.
        walk_length (float): Walking distance in meters.
        weight_factor (float): Weighting factor for distance traveled by mode.

    Returns:
        Optional[float]: Final weighted distance or None on routing failure.
    """
    try:
        origin_node = ox.distance.nearest_nodes(G_mode_canton, origin.x, origin.y)
        nearest_node_mode = ox.distance.nearest_nodes(G_mode_canton, best_nearest.x, best_nearest.y)
        mode_length = nx.shortest_path_length(G_mode_canton, origin_node, nearest_node_mode, weight="length") * weight_mode
    except Exception as e:
        logger.error(f"Error while computing mode path: {e}")
        return None

    weighted_distance = (walk_length + mode_length) * weight_factor
    return weighted_distance

async def compute_weighted_distance(
    dest: Point, 
    modes: List[str], 
    nearest_points: Union[Point, Iterable[Point]], 
    mode: TransportModes,
    G: nx.MultiDiGraph,
    walk_length: Optional[float],
    mode_priority: Dict[str, int],
    base_max_distance: int,
    boost_factor:float,
    priority_boost_factor: float,
    weight_factor_base: float
) -> Tuple[Optional[float], Optional[Point], Optional[float]]:
    """
    Computes the best access point and walk segment for a given candidate destination.

    If walk distance exceeds max thresholds (with boosts), the candidate is skipped.

    Args:
        dest (Point): Destination point under evaluation.
        modes (List[str]): Available modes at the destination.
        nearest_points (Point | Iterable[Point]): Nearby access locations.
        mode (TransportModes): Transport mode to evaluate.
        G (MultiDiGraph): Walking network graph.
        walk_length (Optional[float]): Cached walk distance, if available.
        mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base: 
            Mode weighting and distance parameters.

    Returns:
        Tuple[Optional[float], Optional[Point], Optional[float]]:
            - Weight factor (for later use)
            - Best access point (nearest)
            - Unweighted walk distance (meters)
    """
    if isinstance(nearest_points, Point):
        nearest_points = [nearest_points]
    elif not isinstance(nearest_points, IterableABC):
        logger.warning(f"Invalid nearest points format for {dest}: {nearest_points}")
        return None, None, None
    
    stored = False
    best_nearest = None
    best_walk_length = float('inf')
    
    if walk_length:
        best_walk_length = walk_length
        best_nearest = nearest_points[0]
        stored=True
    else:
        try:
            dest_node = ox.distance.nearest_nodes(G, dest.x, dest.y)
            for nearest in nearest_points:
                nearest_node = ox.distance.nearest_nodes(G, nearest.x, nearest.y)
                walk_length = nx.shortest_path_length(G, dest_node, nearest_node, weight="length")
                if walk_length < best_walk_length:
                    best_walk_length = walk_length
                    best_nearest = nearest
        except Exception as e:
            logger.error(f"Error while finding best nearest: {e}")
            return None, None, None

    if best_nearest is None:
        return None, None, None
    
    if not stored:
        await distance_cache.set_cached_nearest(dest, best_nearest, mode, best_walk_length)
        
    weight_factor = distance_weights(
        modes, best_walk_length, mode_priority,
        base_max_distance, boost_factor, priority_boost_factor, weight_factor_base
    )
    if not weight_factor:
        return None, None, None
    
    return weight_factor, best_nearest, walk_length

async def evaluate_best_candidate(
    origin: Point,
    candidates: List[Tuple[Point, List[str]]],
    get_stored: Callable[[Point], Tuple[Optional[Point], Optional[float]]],
    get_nearest: Callable[[Point], Union[Point, Iterable[Point]]],
    mode: TransportModes,
    G: nx.MultiDiGraph,
    max_destinations: int = MAX_DESTINATIONS
) -> Tuple[Optional[Point], Optional[Point], Optional[float]]:
    """
    Evaluates a list of destination candidates and selects the most reachable one.

    The evaluation considers walking distance to a mode-specific station/parking spot and 
    the travel path from origin to that access point. It uses pre-cached distances where available.

    Args:
        origin (Point): Starting point.
        candidates (List[Tuple[Point, List[str]]]): List of (destination, mode list) tuples.
        get_stored (Callable): Function retrieving cached nearest station for a destination.
        get_nearest (Callable): Function returning one or more nearest Points for a given destination.
        mode (TransportModes): Current transport mode for weighting.
        G (nx.MultiDiGraph): Walking network graph for distance evaluation.
        max_destinations (int): Max number of candidates to evaluate.

    Returns:
        Tuple[Optional[Point], Optional[Point], Optional[float]]:
            - Best destination
            - Associated nearest station
            - Walking time (in minutes)
    """
    best_destination = best_nearest = best_walking = None
    best_weighted_distance = float("inf")
    processed_destinations = 0
    
    (mode_priority, base_max_distance, boost_factor, 
     priority_boost_factor, weight_factor_base, weight_mode
     ) = params_distance_calculation(mode)
    
    _, _, G_mode_canton = get_graph(mode)

    for dest, modes in candidates:
        if processed_destinations >= max_destinations:
            break
        
        walk_length = None
        nearest_points, best_walking = get_stored(dest)
        if not nearest_points:
            cached = distance_cache.get_cached_nearest(dest, mode)
            if cached:
                nearest_point, walk_length = cached
                best_walking = math.ceil(walk_length / WALKING_SPEED / 60)
                nearest_points = [nearest_point]
                logger.debug(f"Using cached nearest for {dest}: {nearest_point}")
            else:
                nearest_points = get_nearest(dest)
        else:
            if best_walking:
                walk_length = best_walking * WALKING_SPEED * 60

        weight_factor, nearest, walk_length = await compute_weighted_distance(dest, modes, nearest_points, mode, G, walk_length,
                                                                              mode_priority, base_max_distance, boost_factor, 
                                                                              priority_boost_factor, weight_factor_base
                                                                              )
        if weight_factor is None or nearest is None:
            continue
        
        weighted_distance= compute_mode_distance(origin, G_mode_canton, nearest, 
                                                weight_mode, walk_length, weight_factor)

        if weighted_distance is None:
            continue

        logger.debug(f"Computed weighted distance for {dest}: {weighted_distance:.2f} m")

        if weighted_distance < best_weighted_distance:
            best_weighted_distance = weighted_distance
            best_destination, best_nearest, best_walking = dest, nearest, best_walking

        if best_weighted_distance == 0:
            return best_destination, best_nearest, best_walking
        
        processed_destinations+=1

    if not best_destination:
        logger.warning("No valid nearest station found after evaluating all candidates.")

    return best_destination, best_nearest, best_walking