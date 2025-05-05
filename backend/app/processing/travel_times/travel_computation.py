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
import sys
from typing import Dict, List, Optional, Tuple, Callable, Union

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
from app.utils.mode_utils import select_parameters, get_travel_mode_and_xml

logger = logging.getLogger(__name__)
    
    
async def run_in_batches(
    tasks: List[Callable[[], asyncio.Future]],  
    batch_size: int = 50,
    desc: str = "Processing",
    abort_condition: Optional[
        Callable[[Union[
            Tuple[Optional[Point], Optional[float], Optional[str]], 
            Optional[str]]], bool]
    ] = None,
    timeout_per_task: int = 600
) -> List:
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
        List: List of all task results, including partial results if aborted.
    """

    async def safe_await(task_factory, task_index):
        """
        Runs a coroutine with timeout and structured error handling.

        Wraps a coroutine factory with `asyncio.wait_for`, logging timeouts,
        cancellations, or unexpected errors. Returns a fallback error string
        if any exception is raised.

        Args:
            task_factory (Callable): Function that returns an awaitable coroutine.
            task_index (int): Index of the task (for logging context).

        Returns:
            Any: Result of the coroutine, or string error message on failure.
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
    transformer: Transformer
) -> Tuple[TravelData, bool, Optional[str]]:
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

    Returns:
        Tuple[TravelData, bool, Optional[str]]:
            - Updated `travel_data` with point-specific times.
            - `True` if the center was resolved and at least some points were processed.
            - Optional rate limit error message (if OJP API fails).
    """
    travel_times: List[float] = []
    valid_points: List[Point] = []
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
        return travel_data, False, None
    
    async def wrapped_process_single_point(point: Point, *args, **kwargs
    )-> Tuple[Optional[Point], Optional[float], Optional[str]]:
        """
        Wrapper for `process_single_point` that sets the current
        logging context to this point before processing.

        Args:
            point (Point): The radial point being processed.

        Returns:
            Tuple[Optional[Point], Optional[float], Optional[str]]: Result of point computation.
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
        abort_condition=lambda r: isinstance(r, tuple) and r[2] and "error: 429" in r[2],
        timeout_per_task=900
    )

    for result in results:
        if result[0]:
            rate_limit_flag = result[2]
            if rate_limit_flag:
                break
        
            valid_points.append(result[0])
            travel_times.append(result[1])
    
    logger.info(f"Successfully processed {len(valid_points)} / {len(points)} points.")

    await store_point_travel_time(mode, center, valid_points, travel_times, travel_data)
    return travel_data, True, rate_limit_flag