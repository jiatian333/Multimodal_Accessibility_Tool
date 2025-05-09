"""
Multimodal Travel Time Computation Module

This module calculates travel times for various transport modes.
It supports both network-wide isochrone computation from sampled origin points, and 
point-based isochrones from a single origin to multiple destinations.


Key Features:
-------------
- Async CPU-parallel travel time computations, and progress tracking via `tqdm`
- Batch control with cancellation on failure or API rate limit
- Modular design for network-wide and point-based routing
- Intelligent fallback on cache hits to avoid recomputation

Main Functions:
---------------
- `network_travel_times_async`: Computes travel times from a list of origin points to multimodal destinations.
- `point_travel_times_async`: Computes travel times from a single center to multiple points for point isochrone generation.
- `run_in_batches`: General-purpose batch runner with timeout, abort condition, and progress display.
- `point_travel_times_performance(...)`: Computes and parses OJP-based travel times to multiple endpoints (used for performance reasons).

External Dependencies:
----------------------
- `networkx`, `osmnx`: Graph-based shortest path routing
- `shapely`, `pyproj`: Geometric operations and coordinate projection
- `rtree`: Spatial indexing for nearest-facility lookup
- `pandas`: Metadata for public transport stations
- App-specific utilities: request processing, station selection, caching

Example:
--------
    from app.processing.travel_times.travel_computation import network_travel_times_async

    travel_data, error = network_travel_times_async(...)
"""

import asyncio
import logging
import requests
import sys
from typing import (
    Dict, List, Optional, Tuple, Union,
    Callable, TypeVar, Awaitable, Set
)
import networkx as nx
import pandas as pd
from pyproj import Transformer
from rtree.index import Index
from shapely.geometry import Point, Polygon
from tqdm import tqdm
import math

from app.core.config import RENTAL_MODES, TransportModes
from app.core.data_types import TravelData, TravelDataMode
from app.core.logger import set_point_context
from app.data.travel_data import store_point_travel_time
from app.processing.travel_times.async_helpers import (
    process_single_network_point,
    process_single_point,
)
from app.processing.travel_times.point_travel_logic import resolve_origin_station
from app.requests.parse_response import parse_trip_response
from app.utils.mode_utils import (
    select_parameters, get_travel_mode_and_xml, mode_selection
)
from app.utils.ojp_helpers import (
    query_ojp_travel_time, RateLimitExceededError
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
    
async def run_in_batches(
    tasks: List[Callable[[], Awaitable[T]]],  
    batch_size: int = 50,
    desc: str = "Processing",
    abort_condition: Optional[Callable[[Union[T, str]], bool]] = None,
    timeout_per_task: int = 600
) -> List[Union[T, str]]:
    """
    Runs a sequence of coroutine factories in async batches with timeout and progress bar.

    Each batch is run concurrently up to `batch_size`. Each task has a max duration
    of `timeout_per_task` seconds. Batches may be cancelled early if `abort_condition`
    is triggered by any task result (e.g., OJP rate limit error).

    Args:
        tasks (List[Callable]): Functions returning coroutine objects (not already awaited).
        batch_size (int): Max number of tasks to run in parallel.
        desc (str): Description label for the progress bar.
        abort_condition (Callable, optional): Function that checks if execution should be aborted.
        timeout_per_task (int): Max duration (in seconds) per task before timeout.

    Returns:
        List[T]: Results from each coroutine task, or partial results if aborted early.
    """

    async def safe_await(
        task_factory: Callable[[], Awaitable[T]], 
        task_index: int
    ) -> Union[T, str]:
        """
        Runs a coroutine with timeout and structured error handling.

        Wraps a coroutine factory with `asyncio.wait_for`, logging timeouts,
        cancellations, or unexpected errors. Returns a fallback error string
        if any exception is raised.

        Args:
            task_factory (Callable): Function that returns an awaitable coroutine.
            task_index (int): Index of the task (for logging context).

        Returns:
            Union[T, str]: Result of the coroutine, or string error message on failure.
        """
        try:
            coro = task_factory()
            return await asyncio.wait_for(coro, timeout=timeout_per_task)
        except asyncio.TimeoutError:
            logger.error(f"Task {task_index} timed out after {timeout_per_task} seconds.")
            return "error: timeout"
        except asyncio.CancelledError:
            logger.error(f"Task {task_index} was cancelled.")
            return "error: cancelled"
        except requests.exceptions.ConnectionError:
            logger.error(f'Task {task_index} exceeded the max retries to connect to the OJP API.')
            return "error: max retries"
        except RateLimitExceededError as e:
            logger.error(f"Rate limit hit during execution: {e}")
            return "error: 429, rate limit exceeded for the OJP API"
        except Exception as e:
            logger.exception(f"Unhandled exception in task {task_index}: {e}")
            return f"error: {str(e)}"

    results = []
    total_batches = math.ceil(len(tasks) / batch_size)
    abort_triggered = False

    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        logger.info(f"Running batch {i // batch_size + 1} of {total_batches} ({len(batch)} tasks)")

        bar = tqdm(
            total=len(batch),
            desc=f"{desc} ({i+1}-{i+len(batch)})",
            unit="pts",
            dynamic_ncols=True,
            leave=True,
            file=sys.stdout
        )

        wrapped_coros = [
            safe_await(task_factory, i + idx)
            for idx, task_factory in enumerate(batch)
        ]
        pending = [asyncio.create_task(coro) for coro in wrapped_coros]
        batch_results = []

        try:
            for finished in asyncio.as_completed(pending):
                try:
                    result = await finished
                    batch_results.append(result)
                except Exception as e:
                    logger.exception(f"Exception in finished task: {e}")
                    batch_results.append(f"error: {str(e)}")
                finally:
                    bar.update(1)
                    bar.refresh()
                    sys.stdout.flush()

                if abort_condition and abort_condition(batch_results[-1]):
                    logger.warning("Abort condition met. Cancelling remaining tasks...")
                    abort_triggered = True
                    for p in pending:
                        p.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    break
        finally:
            bar.close()

        results.extend(batch_results)

        if abort_triggered:
            logger.warning("Aborting further batches due to abort condition.")
            break

    return results

async def network_travel_times_async(
    travel_data: TravelData,
    random_points: List[Point],
    G: nx.MultiDiGraph,
    polygon: Polygon,
    idx: Dict[str, Index],
    public_transport_stations: pd.DataFrame,
    mode: TransportModes,
    arr: str,
    timestamp: str,
    transformer: Transformer
) -> Tuple[TravelData, Optional[str]]:
    """
    Asynchronously computes multimodal travel times from multiple origin sample points to valid destinations.
    
    This function launches parallel computation over all random origin points and supports 
    standard modes (e.g., walk, cycle) as well as shared mobility services (e.g., bicycle_rental, car_sharing). 
    It includes rental-specific logic for splitting trips into:
    - Walking to a rental station
    - Riding via the selected mode
    - Walking from the nearest POI to final destination

    For each point (processed in parallel, using batched execution):
    - It skips previously processed points based on cache.
    - It attempts to use cached rental journeys if available.
    - Fallback to POI search and full route computation if not cached.

    Args:
        travel_data (TravelData): Central cache structure to store and retrieve computed travel times.
        random_points (List[Point]): Sampled geographic origin points.
        G (nx.MultiDiGraph): Walking network graph.
        polygon (Polygon): Valid search area boundary (e.g., city limits).
        idx (Dict[str, Index]): R-tree indices for spatial lookups (by mode).
        public_transport_stations (pd.DataFrame): PT station metadata for POI relevance.
        mode (TransportModes): Mode of transport being evaluated.
        arr (str): ISO 8601 formatted desired arrival time.
        timestamp (str): ISO 8601 current timestamp.
        transformer (Transformer): Coordinate transformation (WGS84 to analysis CRS).

    Returns:
        Tuple[TravelData, Optional[str]]: Updated `travel_data` with computed values, and
        an optional error string if the OJP API's rate limit is exceeded.
    """
    successful_points: int = 0
    already_processed_points: int = 0
    rate_limit_flag: Optional[str] = None
    mode_data: TravelDataMode = travel_data[mode]
    rental: bool = mode in RENTAL_MODES
    
    async def wrapped_process_single_network_point(point: Point, *args, **kwargs
    )-> Optional[str]:
        """
        Wrapper for `process_single_network_point` that sets the current
        logging context to this point before processing.

        Args:
            point (Point): The random point being processed.

        Returns:
            Optional[str]: Result of network computation.
        """
        set_point_context(point)
        return await process_single_network_point(point, *args, **kwargs)
    
    tasks = [
        lambda p=point: wrapped_process_single_network_point(
            p, mode_data, travel_data, G, polygon, idx,
            public_transport_stations, mode, arr, timestamp, transformer, rental
        )
        for point in random_points
    ]

    results = await run_in_batches(
        tasks,
        batch_size=20,
        desc="Computing network travel times",
        abort_condition=lambda r: isinstance(r, str) and "error: 429" in r,
        timeout_per_task=900
    )

    for code in results:
        if not code:
            logger.warning("Task returned None — treating as unknown error")
            continue
        elif "error: 429" in code:
            rate_limit_flag = code
            break
        elif code == "already_processed":
            already_processed_points += 1
        elif code =="success":
            successful_points += 1
        elif code:
            logger.warning(code)
            

    logger.info(f"Successfully processed and stored {successful_points} out of {len(random_points)} points.")
    logger.info(f"{already_processed_points} points were already stored in the database.")

    return travel_data, rate_limit_flag


async def point_travel_times_async(
    travel_data: TravelData,
    center: Point,
    points: List[Point],
    idx: Dict[str, Index],
    G: nx.MultiDiGraph,
    polygon: Polygon,
    public_transport_modes: pd.DataFrame,
    mode: TransportModes, 
    arr: str,
    timestamp: str,
    transformer: Transformer,
    performance: bool
) -> Tuple[TravelData, bool, Optional[str], Optional[Set[str]], Optional[Set[str]]]:
    """
    Asynchronously computes travel times from a single center point to multiple destination points.
    Uses true CPU parallelism for resolving and routing points efficiently.

    This is used for generating point-based isochrones and supports standard and rental modes.
    For rental modes, it resolves:
    - The origin rental station (or parking)
    - The walking time to reach it
    - An optional destination-side rental station
    - The final walking segment from the destination station

    Travel times are computed using either OJP or walking network routing depending on the mode.
    Batched and parallelized with timeout and error detection (e.g., OJP API).
    
    Note that for performance mode, everything is calculated within OJP internally for improved speed, 
    at the cost of having less control and more invalid results being returned. Additionally, 
    sets of modes and stations that were used during the computation are returned. 

    Args:
        travel_data (TravelData): Dictionary storing cached and new travel time results.
        center (Point): The origin coordinate of the isochrone (in WGS84).
        points (List[Point]): Destination points to calculate the travel time to.
        idx (Dict[str, Index]): R-tree indices to quickly find nearby POIs or stations.
        G (nx.MultiDiGraph): Walking network graph.
        polygon (Polygon): Bounding area polygon (usually city limits).
        public_transport_modes (pd.DataFrame): Optional filtering information for PT POIs.
        mode (TransportModes): Travel mode under analysis (e.g., 'walk', 'car_sharing').
        arr (str): Arrival time (ISO 8601).
        timestamp (str): Current time (ISO 8601).
        transformer (Transformer): CRS transformer used for routing.
        performance (bool): Toggles the complete use of OJP to boost performance significantly. 

    Returns:
        Tuple[TravelData, bool, Optional[str], Optional[Set[str]], Optional[Set[str]]]:
            - Updated `travel_data` with point-specific times.
            - `True` if the center was resolved and at least some points were processed.
            - Optional rate limit error message (if OJP API fails).
            - Set of unique modes encountered across all OJP responses (only if performance).
            - Set of unique public transport station names encountered (only if performance).
    """
    travel_times: List[float] = []
    valid_points: List[Point] = []
    if performance:
        valid_points, travel_times, rate_limit_flag, modes, stations = await point_travel_times_performance(
            center, points, mode, timestamp, arr
        )
        if not valid_points:
            return travel_data, False, rate_limit_flag, modes, stations
        await store_point_travel_time(mode, center, valid_points, travel_times, travel_data)
        return travel_data, True, rate_limit_flag, modes, stations
        
    rate_limit_flag: Optional[str] = None
    travel_time_start: float = 0.0
    radius: int = 0
    restriction_type: str = '' 
    poi_filter: str = ''

    rental: bool = mode in RENTAL_MODES
    if rental:
        radius, restriction_type, poi_filter = select_parameters(mode, rental=rental)
    travel_mode, mode_xml = get_travel_mode_and_xml(mode)

    start, travel_time_start, travel_data = await resolve_origin_station(
        center, mode, rental, travel_data, idx, G, polygon,
        timestamp, transformer, arr, public_transport_modes,
        radius, restriction_type, poi_filter
    )

    if start is None:
        return travel_data, False, None, None, None
    
    async def wrapped_process_single_point(point: Point, *args, **kwargs
    )-> Tuple[Optional[Point], Optional[float]]:
        """
        Wrapper for `process_single_point` that sets the current
        logging context to this point before processing.

        Args:
            point (Point): The radial point being processed.

        Returns:
            Tuple[Optional[Point], Optional[float]]: Result of point computation.
        """
        set_point_context(point)
        return await process_single_point(point, *args, **kwargs)
    
    tasks = [
        lambda p=radial_point: wrapped_process_single_point(
            p, travel_data, center, mode, rental, start, travel_time_start,
            idx, G, polygon, timestamp, transformer, arr,
            public_transport_modes, radius, restriction_type, poi_filter,
            travel_mode, mode_xml
        )
        for radial_point in points
    ]
    
    results = await run_in_batches(
        tasks,
        batch_size=50,
        desc="Computing point times",
        abort_condition=lambda r: isinstance(r, str) and "error: 429" in r,
        timeout_per_task=900
    )

    for result in results:
        if isinstance(result, tuple) and result[0] and result[1]:
            valid_points.append(result[0])
            travel_times.append(result[1])
        elif isinstance(result, str) and "error: 429" in result:
            rate_limit_flag = result
            break
    
    logger.info(f"Successfully processed {len(valid_points)} / {len(points)} points.")

    await store_point_travel_time(mode, center, valid_points, travel_times, travel_data)
    return travel_data, True, rate_limit_flag, None, None


async def point_travel_times_performance(
    center: Point,
    points: List[Point],
    mode: TransportModes,
    timestamp: str,
    arr: str
) -> Tuple[List[Point], List[float], Optional[str], Set[str], Set[str]]:
    """
    Asynchronously computes OJP travel times from a central point to a list of destination points.

    Uses the OJP API in full_trip mode to extract not only travel durations but also used transport
    modes and visited public transport stations. Aggregates unique modes/stations across all points.

    Args:
        center (Point): Origin location (in EPSG:4326) from which all trips start.
        points (List[Point]): List of destination points to calculate travel times for.
        mode (TransportModes): Transport mode identifier (e.g., "bicycle_rental").
        timestamp (str): Current request timestamp in ISO-8601 format.
        arr (str): Arrival time in ISO-8601 format.

    Returns:
        Tuple[List[Point], List[float], Optional[str], Set[str], Set[str]]:
            - List of destination points with valid OJP responses.
            - Corresponding list of travel times in minutes.
            - Error string (e.g., "429" rate limit) or None.
            - Set of unique transport modes used.
            - Set of unique public transport station names encountered.
    """
    mode_xml = mode_selection(mode)
    travel_mode, _ = get_travel_mode_and_xml(mode)
    
    valid_points: List[Point] = [p for p in points if center.equals(p)]
    travel_times: List[float] = [0.0] * len(valid_points)
    all_modes: Set[str] = set()
    all_stations: Set[str] = set()
    
    async def bind_point_with_result(
        point: Point, 
        coro: Awaitable[Union[str, float, Tuple[float, List[str], List[str]], None]]
    ) -> Tuple[Point, Union[str, float, Tuple[float, List[str], List[str]], None]]:
        """
        Executes a coroutine and binds the given point to its result.

        Used to ensure the result can be reliably matched with the point that initiated it.

        Args:
            point (Point): The destination point.
            coro (Awaitable): The coroutine to execute.

        Returns:
            Tuple[Point, Union[str, float, Tuple[float, Set[str], Set[str]]]]: 
                The original point and its corresponding result.
        """
        try:
            result = await coro
            return point, result
        except Exception as e:
            logger.exception(f"Error while binding point {point}: {e}")
            return point, f"error: {str(e)}"

    tasks = [
        lambda p=p: bind_point_with_result(
            p,
            query_ojp_travel_time(
            center,
            p,
            mode,
            mode_xml,
            timestamp,
            arr,
            parse_fn=lambda xml, _: parse_trip_response(xml, travel_mode, full_trip=True)
            )
        )
        for p in points if not center.equals(p)
    ]

    raw_results = await run_in_batches(
        tasks,
        batch_size=50,
        desc="OJP Performance Mode",
        abort_condition=lambda r: isinstance(r, str) and "error: 429" in r,
        timeout_per_task=120
    )

    rate_limit_flag = None
    for point, result in raw_results:
        if isinstance(result, str) and "429" in result:
            rate_limit_flag = result
            break
        elif isinstance(result, tuple):
            duration, modes, stations = result
            valid_points.append(point)
            travel_times.append(duration)
            all_modes.update(modes)
            all_stations.update(stations)
        elif isinstance(result, float):
            valid_points.append(point)
            travel_times.append(result)

    return valid_points, travel_times, rate_limit_flag, all_modes, all_stations