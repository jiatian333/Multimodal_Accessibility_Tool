"""
API Endpoint for Isochrone Computation

This module defines the FastAPI route handler responsible for computing isochrones
(network-wide or point-based) based on user-specified parameters. The isochrones 
represent multimodal travel time accessibility and are a core part of the interactive 
urban planning tool.

Key Responsibilities:
---------------------
- Accept POST requests with a set of isochrone computation parameters (`ComputeRequest`).
- Trigger data integrity checks and dataset updates when `force_update` is enabled.
- Generate isochrones based on either full city/canton-wide sampling or specific station input.
- Support improved interpolation with additional point sampling when enabled.
- Handle performance toggles to switch between full and simplified graph/polygon usage.
- Return structured responses indicating success, failure, or rate limiting (`ComputeResponse`).

Main Components:
----------------
1. **ComputeRequest (Pydantic model)**:
   Encapsulates user input including transport mode, timestamp, desired arrival time, 
   and whether to compute network or station-centered isochrones.

2. **ComputeResponse (Pydantic model)**:
   Communicates the outcome of the computation, including status, type, mode, 
   and optional error or reason messages.

3. **compute_isochrones (FastAPI route)**:
   Orchestrates the entire computation process, performing caching, dataset checks,
   travel time calculation, and isochrone generation. Delegates computation to:
   - `handle_network_isochrones`: For asynchronous full-network (city/canton-wide) computation.
   - `handle_point_isochrones`: For asynchronous individual point/station-centered computation.

4. **Dataset Integration**:
   This module interacts with various data sources and processing pipelines:
   - Cached and persisted travel time data.
   - Parking and shared mobility data updates.
   - Station lookup tables and spatial graph data.

5. **Travel Time and Isochrone Logic**:
   Utilizes graph-based routing and spatial sampling to interpolate travel times 
   and create geometric isochrone boundaries using:
   - `generate_adaptive_sample_points`, `sample_additional_points`
   - `generate_radial_grid`
   - `network_travel_times`, `point_travel_times`
   - `generate_isochrones`

Note:
-----
This file assumes supporting components are already available in the `app` package, 
and that certain global configurations (e.g., `IMPROVE_ISOCHRONES`, dataset paths) 
are loaded via `app.core.config`.

Typical Use:
------------
This module is triggered when a POST request is made to the base endpoint (`/`) with
a valid JSON payload. It returns a JSON response describing the computation result.
"""

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Optional, List

from fastapi import APIRouter, Request, BackgroundTasks
from pydantic import BaseModel, model_validator
from shapely.geometry import Point

from app.core.cache import stationary_data
from app.core.config import (
    COMBINED_DATASETS,
    IMPROVE_ISOCHRONES,
    TransportModes,
)
from app.core.data_types import TravelData
from app.data.db_operations import check_entry_exists, save_to_database
from app.data.travel_storage import save_data
from app.data.travel_data import check_travel_data_integrity
from app.data.update_parking import check_for_updates, filter_and_combine_json_files
from app.data.update_shared import process_shared_mobility_data
from app.processing.isochrones.generation import generate_isochrones
from app.processing.travel_times.travel_computation import (
    network_travel_times_async, point_travel_times_async
)
from app.sampling.point_sampling import (
    generate_adaptive_sample_points,
    sample_additional_points,
)
from app.sampling.radial_sampling import generate_radial_grid
from app.utils.mode_utils import get_max_radius

logger = logging.getLogger(__name__)
router = APIRouter()

class ComputeRequest(BaseModel):
    """
    Request model for computing isochrones via the API.

    Attributes:
        mode (TransportModes): Transport mode (e.g., walk, cycle, bicycle_rental).
        network_isochrones (bool): Whether to compute full-network isochrones.
        input_station (Optional[str]): Origin station for point-based isochrones.
        performance (bool): Enable faster computation (less precise). Only for point isochrones.
        arrival_time (Optional[str]): Desired arrival time (ISO format).
        timestamp (Optional[str]): Timestamp of the request (ISO format).
        force_update (Optional[bool]): If True, forces update of parking and shared mobility data.
    """
    
    mode: TransportModes
    network_isochrones: bool
    input_station: Optional[str] = None
    performance: bool = False
    arrival_time: Optional[str] = None
    timestamp: Optional[str] = None
    force_update: Optional[bool] = False
    
    @model_validator(mode='before')
    @classmethod
    def set_arrival_time_default(cls, data):
        data = dict(data or {})
        timestamp_str = data.get("timestamp")
        
        if not timestamp_str:
            timestamp = datetime.now(timezone.utc)
            data["timestamp"] = timestamp.isoformat()
        else:
            timestamp = datetime.fromisoformat(timestamp_str)

        if not data.get("arrival_time"):
            arrival_time = timestamp + timedelta(hours=1)
            data["arrival_time"] = arrival_time.isoformat()

        return data
    
class ComputeResponse(BaseModel):
    """
    Response model for isochrone computation results returned by the API.

    Attributes:
        status (str): Status of the request, e.g., "success", "skipped", "failed" or "partial success".
        type (Optional[str]): Type of isochrone generated — "network" or "point".
        station (Optional[str]): Name of the station used in point isochrone computation.
        mode (Optional[TransportModes]): Transport mode used for the computation.
        reason (Optional[str]): Optional explanation for partial or skipped results.
        error (Optional[str]): Description of any error that occurred during processing.
        runtime (Optional[float]): Runtime of the computation in minutes (used for performance benchmarking).
        used_modes (Optional[List[str]]): All transport modes used in the computed trips (only for performance mode).
        station_names (Optional[List[str]]): All public transport station names involved (only for performance mode).
    """
    
    status: str
    type: Optional[str] = None
    station: Optional[str] = None
    mode: Optional[TransportModes] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    runtime: Optional[float] = None
    used_modes: Optional[List[str]] = None
    station_names: Optional[List[str]] = None

@router.post("/", response_model=ComputeResponse)
async def compute_isochrones(
    req: ComputeRequest, 
    request: Request, 
    background_tasks: BackgroundTasks
) -> ComputeResponse:
    """
    Main API endpoint to compute isochrones.

    Depending on the `network_isochrones` flag, this will call the appropriate
    function to compute either full network or point-based isochrones.

    Args:
        req (ComputeRequest): Request object with computation settings.
        request (Request): FastAPI request object containing app state.
        background_tasks (BackgroundTasks): FastAPI background task handler for deferred persistence.

    Returns:
        ComputeResponse: Success status and metadata or an error message.
    """
    start = time.time()
        
    logger.info(f"Received compute request: {req}")
    
    if check_entry_exists(
        "network" if req.network_isochrones else "point", req.mode, req.input_station if req.input_station else "null"
    ):
        logger.info("Skipping computation: result already exists in database.")
        return ComputeResponse(status="skipped", reason="Already exists in database.")
    
    if req.force_update:
        logger.info("Force update enabled, updating datasets.")
        check_for_updates()
        process_shared_mobility_data()
        filter_and_combine_json_files(
            ["bike-parking", "zurich-bicycles-parking"],
            COMBINED_DATASETS["json_file_bike_parking"], 
            exclude_name="Motorrad"
        )
        filter_and_combine_json_files(
            ["parking-facilities", "zurich-street-parking", "zurich-public-parking-garages"], 
            COMBINED_DATASETS["json_file_car_parking"], 
            include_art=["Blaue Zone", "Weiss markiert"]
        )

    stationary_data.load()
    travel_data = request.app.state.travel_data
    
    if not check_travel_data_integrity(travel_data):
        logger.error("Travel data corrupted.")
        return ComputeResponse(
            status="failed", 
            error="Travel data corrupted. Please validate accuracy before continuing."
        )

    if req.network_isochrones:
        return await compute_network_isochrones(travel_data, req, start, background_tasks)
    else:
        return await compute_point_isochrones(travel_data, req, start, background_tasks)

async def compute_network_isochrones(
    travel_data: TravelData, 
    req: ComputeRequest, 
    start: float, 
    background_tasks: BackgroundTasks
) -> ComputeResponse:
    """
    Computes network-wide isochrones using randomly sampled points.

    Args:
        travel_data (TravelData): Current cached travel time data.
        req (ComputeRequest): Input request with parameters.
        start (float): Starting time of the computation in seconds.
        background_tasks (BackgroundTasks): For scheduling async persistence (e.g., saving data).

    Returns:
        ComputeResponse: Status dictionary with metadata or an error message.
    """
    
    logger.info("Computing network isochrones.")
    random_points = generate_adaptive_sample_points(
        stationary_data.city_poly,
        stationary_data.water_combined,
        stationary_data.target_crs,
        stationary_data.source_crs,
        mode=req.mode
    )

    travel_data, rate_limit_flag = await network_travel_times_async(
        travel_data, random_points, stationary_data.G_canton,
        stationary_data.canton_poly, stationary_data.idx,
        stationary_data.public_transport_stations, req.mode,
        req.arrival_time, req.timestamp, stationary_data.transformer
    )
    background_tasks.add_task(save_data, travel_data)
    
    if rate_limit_flag and "429" in rate_limit_flag:
        return ComputeResponse(
            status="failed", 
            error="Rate limit exceeded while computing network isochrones.",
            runtime=round((time.time() - start) / 60, 2)
        )

    isochrones = generate_isochrones(
        travel_data, req.mode, stationary_data.water_combined,
        stationary_data.city_poly, stationary_data.source_crs,
        stationary_data.target_crs, stationary_data.transformer,
        network_isochrones=True
    )

    if IMPROVE_ISOCHRONES:
        logger.info("Improving isochrones with additional sample points.")
        new_points = sample_additional_points(
            isochrones, stationary_data.city_poly,
            stationary_data.water_combined,
            stationary_data.target_crs,
            stationary_data.source_crs,
            n_unsampled=100, n_large_isochrones=150
        )
        travel_data, rate_limit_flag = await network_travel_times_async(
            travel_data, new_points, stationary_data.G_canton,
            stationary_data.canton_poly, stationary_data.idx,
            stationary_data.public_transport_stations, req.mode,
            req.arrival_time, req.timestamp, stationary_data.transformer
        )
        background_tasks.add_task(save_data, travel_data)

        isochrones = generate_isochrones(
            travel_data, req.mode, stationary_data.water_combined,
            stationary_data.city_poly, stationary_data.source_crs,
            stationary_data.target_crs, stationary_data.transformer,
            network_isochrones=True
        )

    save_to_database(isochrones)
    
    if rate_limit_flag and "429" in rate_limit_flag:
        return ComputeResponse(
            status="partial success", 
            reason="Rate limit exceeded during isochrone improvement.",
            type="network",
            mode=req.mode,
            runtime=round((time.time() - start) / 60, 2)
        )
    
    return ComputeResponse(
        status="success", 
        type="network", 
        mode=req.mode, 
        runtime=round((time.time() - start) / 60, 2)
    )


async def compute_point_isochrones(
    travel_data: TravelData, 
    req: ComputeRequest, 
    start: float,
    background_tasks: BackgroundTasks
) -> ComputeResponse:
    """
    Computes point-based isochrones centered on a specific station asynchronously.

    Args:
        travel_data (TravelData): Current cached travel time data.
        req (ComputeRequest): Input request with parameters.
        start (float): Starting time of the computation in seconds.
        background_tasks (BackgroundTasks): For scheduling async persistence (e.g., saving data).

    Returns:
        ComputeResponse: Status dictionary with metadata or an error message.
    """
    
    logger.info(f"Computing point isochrones for station: {req.input_station}.")
    
    lookup = stationary_data.public_transport_stations.set_index("name")[["longitude", "latitude"]].to_dict("index")
    coords = lookup.get(req.input_station)
    if not coords:
        logger.error(f"Station not found: {req.input_station}.")
        return ComputeResponse(status="failed", error=f"Station '{req.input_station}' not found")
    
    center = Point((coords["longitude"], coords["latitude"]))
    max_radius = get_max_radius(req.mode, req.performance)
    
    points = generate_radial_grid(
        center, stationary_data.canton_poly, stationary_data.water_combined, 
        max_radius, stationary_data.source_crs,
        stationary_data.target_crs, req.mode, req.performance, 
        stationary_data.transformer
    )

    travel_data, success, rate_limit_flag, modes, stations = await point_travel_times_async(
        travel_data, center, points, stationary_data.idx, stationary_data.G_canton, 
        stationary_data.canton_poly, stationary_data.public_transport_stations, 
        mode=req.mode, arr=req.arrival_time, timestamp=req.timestamp, 
        transformer=stationary_data.transformer, performance=req.performance
    )
    
    if rate_limit_flag and "429" in rate_limit_flag:
        return ComputeResponse(
            status="failed", 
            error="Rate limit exceeded while computing point isochrones.", 
            runtime=round((time.time() - start) / 60, 2)
        )
    
    if not success:
        logger.error("Point travel time computation failed — no isochrones generated.")
        return ComputeResponse(
            status="failed", 
            error="Point isochrone computation failed.", 
            reason=f"Mode: {req.mode} not sufficiently available in this region.",
            runtime=round((time.time() - start) / 60, 2)
        )

    background_tasks.add_task(save_data, travel_data)
    
    isochrones = generate_isochrones(
        travel_data, req.mode, stationary_data.water_combined,
        stationary_data.canton_poly, stationary_data.source_crs,
        stationary_data.target_crs, stationary_data.transformer,
        center=center, network_isochrones=False, input_station=req.input_station,
        performance=req.performance
    )
    save_to_database(isochrones)
    
    return ComputeResponse(
        status="success", 
        type="point", 
        station=req.input_station, 
        mode=req.mode, 
        used_modes=modes,
        station_names=stations,
        runtime=round((time.time() - start) / 60, 2)
    )