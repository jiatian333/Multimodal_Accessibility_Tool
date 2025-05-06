"""
Routing Helper Functions for Network Isochrones

This module defines a suite of reusable utilities to support network-based 
isochrone calculations. These functions are invoked during the processing 
of multiple origin points, allowing for modular resolution of:

- Rental station chains (station → POI routing)
- Final destination and walking connections
- Total travel time aggregation and caching

Responsibilities:
-----------------
- Identify routing configuration for rental and non-rental modes.
- Resolve nearest stations and cached travel segments efficiently.
- Orchestrate the composition of walk + main mode + walk trips.
- Cache results to TravelData for reuse across requests.

Key Functions:
--------------
- `should_skip_point(...)`: Checks if a point was already processed.
- `resolve_rental_chain(...)`: Reconstructs cached rental chains or falls back.
- `resolve_destination_and_nearest(...)`: Identifies target POI and access node.
- `resolve_final_destination(...)`: Finalizes valid destination and POI.
- `compute_and_cache_total_travel_time(...)`: Calculates full travel chain time and caches.

Requirements:
-------------
- Called internally by `network_travel_times(...)` in `travel_computation.py`.
- Designed for use with multi-mode processing using OJP and spatial filters.

Usage:
------
    from app.processing.travel_times.network_travel_logic import (
        should_skip_point,
        resolve_rental_chain,
        compute_and_cache_total_travel_time,
        ...
    )

Logging:
--------
- Logs routing resolution failures, cache hits, and travel time issues with full context.
"""


from typing import Tuple, Optional, List, Dict, Union
import logging

import pandas as pd
import networkx as nx
from shapely.geometry import Point, Polygon
from rtree.index import Index
from pyproj import Transformer

from app.core.config import TransportModes, NUM_RESULTS_DESTINATIONS
from app.core.data_types import TravelData, TravelDataMode
from app.data.parking_storage import store_parking
from app.data.rental_storage import (
    get_stored_closest_rental,
    get_stored_rental_station_info,
    store_closest_rental,
    store_rental_station_info,
)
from app.data.travel_data import store_travel_time
from app.utils.request_processing import (
    process_location_request,
    process_and_get_travel_time
)
from app.utils.routing import find_valid_nearest_station
from app.utils.mode_utils import (
    select_parameters, mode_selection, get_travel_mode_and_xml
)

logger = logging.getLogger(__name__)

def should_skip_point(point: Point, mode_data: TravelDataMode) -> bool:
    """
    Checks if a point has already been processed and stored in travel_data.

    Skips redundant computation by detecting previously cached travel times.

    Args:
        point (Point): The origin point to check.
        mode_data (TravelDataMode): The cached data structure for a specific mode.

    Returns:
        bool: True if the point is already processed, False otherwise.
    """
    logger.debug('----------------------------------------------------------')
    if point in mode_data["isochrones"]:
        logger.info(f"Skipping point: {point}, already processed.")
        return True
    return False


async def resolve_rental_chain(
    random_point: Point,
    polygon: Polygon,
    idx: Dict[str, Index],
    mode: TransportModes,
    G: nx.MultiDiGraph,
    travel_data: TravelData,
    timestamp: str,
    public_transport_stations: pd.DataFrame,
) -> Tuple[
    Optional[Point], 
    Optional[Point], 
    Optional[Point], 
    Optional[float], 
    bool, 
    Optional[Point], 
    Optional[float]
]:
    """
    Attempts to resolve rental station and associated cached data for a random origin.

    This function identifies:
    - The closest rental station to the random origin point.
    - Any cached destination and ride time from that rental station.
    - Any cached walking leg from that destination to the POI.

    Args:
        random_point (Point): Origin point to start the chain.
        polygon (Polygon): Area boundary.
        idx (Dict[str, Index]): R-tree index for spatial queries.
        mode (TransportModes): Mode (e.g., bicycle_rental).
        G (nx.MultiDiGraph): Walking network graph.
        travel_data (TravelData): Current travel cache.
        timestamp (str): Request time.
        public_transport_stations (DataFrame): Available PT options.

    Returns:
        Tuple[...] of:
            current_point (Point),
            rental_station (Optional[Point]),
            destination (Optional[Point]),
            travel_time_mode (Optional[float]),
            rental_stored (bool),
            nearest (Optional[Point]),
            travel_time_walk (Optional[float])
    """
    radius, restriction_type, poi_filter = select_parameters(mode, rental=True)
    rental_station, _, _, _ = await process_location_request(
        random_point, radius, restriction_type, poi_filter, polygon, idx,
        mode, G, travel_data, timestamp, num_results=1, rental=True,
        public_transport_modes=public_transport_stations
    )
    if not rental_station:
        return None, None, None, None, False, None, None

    rental_station = rental_station[0]
    logger.debug(f"Closest rental station: {rental_station}")
    
    destination, travel_time_mode = get_stored_rental_station_info(travel_data, mode, rental_station)
    if destination and travel_time_mode:
        nearest, travel_time_walk = get_stored_closest_rental(
            travel_data, mode, destination, point_isochrones=False
        )
        logger.info('Stored Rental Information found and retrieved')
        return random_point, rental_station, destination, travel_time_mode, True, nearest, travel_time_walk 

    return rental_station, rental_station, None, None, False, None, None


async def resolve_destination_and_nearest(
    current_point: Point,
    polygon: Polygon,
    idx: Dict[str, Index],
    mode: TransportModes,
    G: nx.MultiDiGraph,
    travel_data: TravelData,
    timestamp: str,
    public_transport_stations: pd.DataFrame,
    rental: bool
) -> Tuple[
    Union[Point, List[Point]],
    List[List[str]],
    Optional[Point],
    Optional[float],
    str,
    str
]:
    """
    Finds a valid set of destination POIs and the nearest routing node.

    Performs a spatial lookup (and optionally mode filtering) to find potential
    destinations, the closest access node, and walking time from access node.

    Args:
        current_point (Point): Point to search destinations from.
        polygon (Polygon): Spatial restriction polygon.
        idx (Dict[str, Index]): R-tree indices for routing.
        mode (TransportModes): Processing mode.
        G (nx.MultiDiGraph): Walking graph.
        travel_data (TravelData): Cached time dictionary.
        timestamp (str): Request time.
        public_transport_stations (DataFrame): Public transit metadata.
        rental (bool): Flag to include rental-specific filters.

    Returns:
        Tuple:
            destination (Union[Point, List[Point]]),
            modes (List[List[str]]),
            nearest (Optional[Point]),
            travel_time_walk (Optional[float]),
            travel_mode (str),
            mode_xml (str)
    """
    radius, restriction_type, poi_filter = select_parameters(mode)
    num_results = NUM_RESULTS_DESTINATIONS if mode != 'walk' else 1
    destination, modes, nearest, travel_time_walk = await process_location_request(
        current_point, radius, restriction_type, poi_filter,
        polygon, idx, mode, G, travel_data, timestamp,
        num_results=num_results, rental=rental,
        public_transport_modes=public_transport_stations
    )
    
    travel_mode, mode_xml = get_travel_mode_and_xml(mode)
    return destination, modes, nearest, travel_time_walk, travel_mode, mode_xml


async def resolve_final_destination(
    origin: Point,
    mode: TransportModes,
    rental: bool,
    rental_stored: bool,
    idx: Dict[str, Index],
    destination: Union[Point, List[Point]],
    travel_data: TravelData,
    nearest: Optional[Point],
    travel_time_walk: Optional[float],
    G: nx.MultiDiGraph,
    modes: List[List[str]],
    polygon: Polygon
) -> Tuple[Optional[Point], Optional[Point], Optional[float]]:
    """
    Finalizes the destination and nearest POI selection after candidate search.

    Depending on the transport mode:
    - For rentals: selects the precomputed nearest rental point unless already cached.
    - For private modes (e.g., car, cycle): finds the best parking station using weighted evaluation.

    Args:
        origin (Point): Starting point of the journey.
        mode (TransportModes): Current mode.
        rental (bool): If rental logic is enabled.
        rental_stored (bool): Whether data is cached.
        idx (Dict[str, Index]): R-tree index.
        destination (Union[Point, List[Point]]): Candidate destination(s).
        travel_data (TravelData): Cache dictionary.
        nearest (Optional[Point]): Closest access node.
        travel_time_walk (Optional[float]): Walk duration.
        G (nx.MultiDiGraph): Walking graph.
        modes (List[List[str]]): Transport modes per candidate.
        polygon (Polygon): Polygon to constrain results.

    Returns:
        Tuple:
            destination (Point),
            nearest (Point),
            travel_time_walk (Optional[float])
    """
    if mode != 'walk':
        if not rental:
            return await find_valid_nearest_station(
                origin, idx, destination, mode, travel_data, 
                G, public_transport_modes=modes, polygon=polygon
            )
        elif not rental_stored:
            return destination[0], nearest, travel_time_walk
    else:
        return destination[0], nearest, travel_time_walk
    
    return destination, nearest, travel_time_walk

async def compute_and_cache_total_travel_time(
    mode: TransportModes,
    mode_xml: Optional[str],
    travel_mode: Optional[str],
    current_point: Point,
    rental_stored: bool,
    rental: bool,
    random_point: Point,
    rental_station: Optional[Point],
    nearest: Optional[Point],
    destination: Point,
    travel_time_mode: Optional[float],
    travel_time_walk: Optional[float],
    G: nx.MultiDiGraph,
    arr: str,
    timestamp: str,
    transformer: Transformer, 
    travel_data: TravelData
) -> Optional[float]:
    """
    Aggregates total travel time for a trip and updates the cache.

    Supports three-stage trip structure:
    - Walk to rental station (if applicable)
    - Main travel segment (e.g., cycle, car, walk)
    - Final walk to destination (if applicable)

    Args:
        mode (TransportModes): Current mode.
        mode_xml (Optional[str]): XML format for OJP. None if rental_stored.
        travel_mode (Optional[str]): Mapped internal travel mode. None if rental_stored.
        current_point (Point): Start of travel.
        rental_stored (bool): Whether data is cached.
        rental (bool): Whether mode uses rental logic.
        random_point (Point): Original sample origin.
        rental_station (Optional[Point]): Access station.
        nearest (Optional[Point]): POI used for routing.
        destination (Point): Final destination.
        travel_time_mode (Optional[float]): Mode-specific ride time.
        travel_time_walk (Optional[float]): Final walk duration.
        G (nx.MultiDiGraph): Walking network.
        arr (str): Desired arrival time.
        timestamp (str): Request timestamp.
        transformer (Transformer): CRS transformer.
        travel_data (TravelData):  Cache structure to update.

    Returns:
        Optional[float]]: Computed travel time.
    """
    travel_time = 0.0

    if mode != 'walk':
        if not rental_stored:
            travel_time_mode = await process_and_get_travel_time(
                current_point, nearest, mode_xml, travel_mode, G, arr, timestamp, transformer
            )
            if travel_time_mode is None:
                logger.warning("No valid travel time mode. Skipping point!")
                return None
            travel_time += travel_time_mode

        if rental:
            travel_time_walk_start = await process_and_get_travel_time(
                random_point, rental_station, mode_selection('walk'), 'walk', G, arr, timestamp, transformer
            )
            if travel_time_walk_start is None:
                logger.warning("No valid start walking time. Skipping point!")
                return None
            travel_time += travel_time_walk_start

        if travel_time_walk is None:
            travel_time_walk = await process_and_get_travel_time(
                nearest, destination, mode_selection('walk'), 'walk', G, arr, timestamp, transformer
            )
            if travel_time_walk is None:
                logger.warning("Not able to compute final walking time. Skipping point!")
                return None
            if not rental:
                await store_parking(mode, destination, nearest, travel_data, travel_time_walk)
            travel_time += travel_time_walk
            
        if not rental_stored and rental:
            await store_rental_station_info(rental_station, destination, travel_time_mode, mode, travel_data)
            await store_closest_rental(travel_data, mode, destination, nearest, travel_time_walk)

    else:
        travel_time = await process_and_get_travel_time(
            current_point, destination, mode_xml, mode, G, arr, timestamp, transformer
        )
        if travel_time is None:
            logger.warning("Not able to compute walking travel time. Skipping point!")
            return None
    
    await store_travel_time(mode, random_point, destination, travel_time, travel_data)

    return travel_time