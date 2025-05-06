"""
Asynchronous Helpers for Point-Based and Network-Based Travel Time Computations
================================================================================

This module provides helper functions for executing parallelized, asynchronous
computation of travel times from origin points to destination points.

Responsibilities:
-----------------
- Perform true parallel evaluation of travel time per point.
- Handle rental mode logic (e.g., station resolution).
- Skip already-processed points.
- Gracefully handle rate limit exceedances.

Main Functions:
---------------
- `process_single_network_point(...)`: Async handler for one random network sample point (network isochrone mode).
- `process_single_point(...)`: Async handler for one radial point (point isochrone mode).

Dependencies:
-------------
- Requires properly configured graphs, spatial indices, and routing utilities.
- Designed to be invoked by `point_travel_times_async` and `network_travel_times_async`.

Usage:
------
Used internally in async travel time computation pipelines.

"""

import logging
from typing import Dict, List, Optional, Tuple

import networkx as nx
import pandas as pd
from pyproj import Transformer
from rtree.index import Index
from shapely.geometry import Point, Polygon

from app.core.config import TransportModes
from app.core.data_types import TravelData, TravelDataMode
from app.processing.travel_times.point_travel_logic import (
    compute_total_point_time,
    resolve_destination_station,
    should_skip_radial_point,
)
from app.processing.travel_times.network_travel_logic import (
    compute_and_cache_total_travel_time,
    resolve_destination_and_nearest,
    resolve_final_destination,
    resolve_rental_chain,
    should_skip_point,
)
from app.utils.ojp_helpers import RateLimitExceededError

logger = logging.getLogger(__name__)

async def process_single_network_point(
    random_point: Point,
    mode_data: TravelDataMode,
    travel_data: TravelData,
    G: nx.MultiDiGraph,
    polygon: Polygon,
    idx: Dict[str, Index],
    public_transport_stations: pd.DataFrame,
    mode: TransportModes,
    arr: str,
    timestamp: str,
    transformer: Transformer,
    rental: bool
) -> Optional[str]:
    """
    Asynchronously processes a single random point for network-wide travel time computation.

    Handles:
    - Skipping already processed points.
    - Resolving rental chain if rental mode.
    - Resolving final destination and nearest station.
    - Computing total travel time and updating travel_data.
    
    Exceptions:
        This function may raise exceptions (e.g., RateLimitExceededError) during processing.
        Exceptions are expected to be handled by the calling function (e.g., `run_in_batches`).

    Args:
        random_point (Point): Origin random point.
        mode_data (TravelDataMode): Mode-specific cache.
        travel_data (TravelData): Travel time cache.
        G (nx.MultiDiGraph): Walking graph.
        polygon (Polygon): City/canton boundary.
        idx (Dict[str, Index]): R-tree spatial index.
        public_transport_stations (pd.DataFrame): Public transport station metadata.
        mode (TransportModes): Selected transport mode (e.g., walk, bike_rental)
        arr (str): Arrival time ISO 8601.
        timestamp (str): Current timestamp ISO 8601.
        transformer (Transformer): Coordinate transformer.
        rental (bool): Whether using rental mode.

    Returns:
        Optional[str]: One of:
            - "success" if the point was processed successfully.
            - "already_processed" if cached.
        - Informational string (e.g., "No valid destination found.") if point is skipped.
    """
    if should_skip_point(random_point, mode_data):
        return "already_processed"

    rental_station: Optional[Point] = None
    travel_time_mode: Optional[float] = None
    rental_stored: bool = False
    current_point: Point = random_point
    modes: List[List[str]] = []
    mode_xml: Optional[str] = None
    travel_mode: Optional[str] = None
    
    if rental:
        current_point, rental_station, destination, travel_time_mode, rental_stored, nearest, travel_time_walk = await resolve_rental_chain(
            random_point, polygon, idx, mode, G, travel_data, timestamp, public_transport_stations
        )
        if not rental_station:
            return 'No valid rental station found. Skipping!'

    if not rental_stored:
        destination, modes, nearest, travel_time_walk, travel_mode, mode_xml = await resolve_destination_and_nearest(
            current_point, polygon, idx, mode, G, travel_data, timestamp, public_transport_stations, rental
        )
        if not destination:
            return 'No valid destination found. Skipping!'

    destination, nearest, travel_time_walk = await resolve_final_destination(
        current_point, mode, rental, rental_stored, idx, destination, 
        travel_data, nearest, travel_time_walk, G, modes, polygon
    )

    if mode != "walk" and not nearest:
        return 'No valid nearest station found. Skipping point!'
    
    travel_time = await compute_and_cache_total_travel_time(
        mode=mode,
        mode_xml=mode_xml,
        travel_mode=travel_mode,
        current_point=current_point,
        rental_stored=rental_stored,
        rental=rental,
        random_point=random_point,
        rental_station=rental_station,
        nearest=nearest,
        destination=destination,
        travel_time_mode=travel_time_mode,
        travel_time_walk=travel_time_walk,
        G=G,
        arr=arr,
        timestamp=timestamp,
        transformer=transformer,
        travel_data=travel_data
    )

    if travel_time is None:
        return None
    
    logger.debug(f"Total travel time of {travel_time} min from origin={random_point} to destination={destination} using mode={mode}.")
    return "success"


async def process_single_point(
    radial_point: Point,
    travel_data: TravelData,
    center: Point,
    mode: TransportModes,
    rental: bool,
    start: Point,
    travel_time_start: float,
    idx: Dict[str, Index],
    G: nx.MultiDiGraph,
    polygon: Polygon,
    timestamp: str,
    transformer: Transformer,
    arr: str,
    public_transport_modes: pd.DataFrame,
    radius: int,
    restriction_type: str,
    poi_filter: str,
    travel_mode: str,
    mode_xml: str
) -> Tuple[Optional[Point], Optional[float]]:
    """
    Asynchronously processes a single radial point for point-based isochrone computation:
    - Checks if already processed.
    - Resolves destination station (if rental mode).
    - Computes total travel time from origin to destination.
    
    Exceptions:
        This function may raise exceptions (e.g., RateLimitExceededError) during processing.
        Exceptions are expected to be handled by the calling function (e.g., `run_in_batches`).

    Args:
        radial_point (Point): Destination point.
        travel_data (TravelData): Cached travel data.
        center (Point): Origin center for this isochrone computation.
        mode (TransportModes): Mode of travel (walk, car_sharing, etc.).
        rental (bool): Whether mode is rental-based.
        start (Point): Access station point from center.
        travel_time_start (float): Precomputed time to origin station.
        idx (Dict[str, Index]): Spatial R-tree indices.
        G (nx.MultiDiGraph): Walking network graph.
        polygon (Polygon): Polygon for spatial filtering.
        timestamp (str): Processing timestamp ISO 8601.
        transformer (Transformer): CRS transformer.
        arr (str): Arrival timestamp ISO 8601.
        public_transport_modes (pd.DataFrame): Public transport metadata.
        radius (int): Search radius.
        restriction_type (str): POI restriction type.
        poi_filter (str): POI filtering criteria.
        travel_mode (str): Mode used internally for routing engines.
        mode_xml (str): OJP-specific XML representation of the mode.

    Returns:
        Tuple[Optional[Point], Optional[float]]:
            - Destination point if successful.
            - Total travel time in minutes.
    """
    total_time = None
    
    if should_skip_radial_point(radial_point, travel_data[mode], center):
        return None, None

    travel_time_end: float = 0.0
    destination_point: Point = radial_point

    if rental:
        result = await resolve_destination_station(
            radial_point, mode, rental, travel_data, idx, G, polygon,
            timestamp, transformer, arr, public_transport_modes,
            radius, restriction_type, poi_filter
        )
        if result[0] is None:
            return None, None
        destination_point, travel_time_end = result

    total_time = await compute_total_point_time(
        start, destination_point, travel_mode, mode_xml,
        travel_time_start, travel_time_end,
        G, arr, timestamp, transformer
    )

    if total_time is None:
        return None, None

    logger.debug(f"Computed total time {total_time:.2f} min from {center} to {radial_point} using mode {mode}.")
    
    return radial_point, total_time