"""
OJP Helper Functions for Travel and Location Requests

This module provides lower-level utilities to interact with the Open Journey Planner (OJP) API.
It separates core OJP logic from higher-level request orchestration, preventing circular imports
and improving code reusability.

Responsibilities:
-----------------
- Construct and dispatch XML-based trip/location requests to the OJP endpoint.
- Parse and interpret results (durations, POIs, modes).
- Handle walking fallback using local networks.
- Handle API-specific errors such as rate limits.

Key Functions:
--------------
- `process_trip_request`: Sends a trip request for routing between origin and destination.
- `location_ojp`: Requests location-based POIs (e.g., stops, rentals) using OJP.
- `query_ojp_travel_time`: Generic travel time request with customizable parsing logic.

Exceptions:
-----------
- `RateLimitExceededError`: Raised when OJP returns HTTP 429.

Usage:
------
    from app.utils.ojp_helpers import (
        process_trip_request,
        location_ojp,
        query_ojp_travel_time,
        RateLimitExceededError
    )
"""


import logging
from typing import Tuple, List, Optional, Union, Callable

from shapely.geometry import Point

from app.core.config import ENDPOINT, RENTAL_MODES, TransportModes
from app.requests.build_request import (
    create_trip_request, create_location_request, send_request
)
from app.requests.parse_response import (
    check_trip_response, parse_location_response
)

logger = logging.getLogger(__name__)


async def process_trip_request(
    random_point: Point,
    destination: Point,
    mode_xml: str,
    extension_start: str,
    extension_end: str,
    arr: str,
    timestamp: str, 
    num_results: int = 1,
    **kwargs
) -> Tuple[str, str]:
    """
    Asynchronously builds and sends a trip request using the OJP service.

    Args:
        random_point (Point): Origin point in WGS84 coordinates.
        destination (Point): Destination point in WGS84 coordinates.
        mode_xml (str): Mode definition for the XML payload.
        extension_start (str): XML extension block before trip legs.
        extension_end (str): XML extension block after trip legs.
        arr (str): ISO-formatted arrival time string.
        timestamp (str): Time of request (ISO 8601 format).
        num_results (int): Number of journey results to request.
        **kwargs: Additional keyword arguments passed to the request builder.

    Returns:
        Tuple[str, str]: Raw XML response and a status check string.
    """
    request = create_trip_request(
        timestamp, random_point, destination,
        arr=arr,
        mode_xml=mode_xml,
        extension_start=extension_start,
        extension_end=extension_end,
        num_results=num_results,
        **kwargs
    )
    response, code = await send_request(request, ENDPOINT)
    code = check_trip_response(response, code)
    return response, code

async def location_ojp(
    random_point: Point,
    num_results: int,
    include_pt_modes: bool,
    radius: int,
    restriction_type: str,
    poi_filter: str, 
    timestamp: str
) -> Tuple[Optional[List[Point]], Optional[List[List[str]]]]:
    """
    Asynchronously sends an OJP location request to find nearby transport facilities.

    Args:
        random_point (Point): Center of the search area.
        num_results (int): Number of POIs to request.
        include_pt_modes (bool): Whether to include public transport modes.
        radius (int): Search radius in meters.
        restriction_type (str): Type of place to look for ('stop', 'poi').
        poi_filter (str): Concrete POI filter.
        timestamp (str): Current time of request (ISO 8601 format).

    Returns:
        Tuple[List[Point], List[List[str]]]: Found destination points and associated mode lists.
    """
    request = create_location_request(
        timestamp,
        random_point,
        num_results=num_results,
        include_pt_modes=include_pt_modes,
        radius=radius,
        restriction_type=restriction_type,
        poi_filter=poi_filter
    )
    
    logger.debug(
        f"Sending location request from point ({random_point.y}, {random_point.x}), "
        f"radius={radius}, type={restriction_type}"
    )

    response, code = await send_request(request, ENDPOINT)
    
    logger.debug(f"Status code received from OJP: {code}")

    if code == 429:
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    if code != 200:
        logger.warning("No valid response from OJP. Skipping location request.")
        return None, None
    
    poi_list = parse_location_response(response, restriction_type)
    
    logger.debug(f"Received {len(poi_list)} POIs from OJP for type '{restriction_type}'")
    
    destinations, modes = (
        list(t) for t in zip(*[(Point(i['longitude'], i['latitude']), i['modes']) for i in poi_list])
    ) if poi_list else ([], [])
    
    if not destinations:
        logger.warning("No POIs found in location_ojp response.")
    
    logger.debug(f"Received {len(destinations)} destinations from OJP for point {random_point}")
    return destinations, modes

async def query_ojp_travel_time(
    start: Point,
    end: Point,
    mode: TransportModes,
    mode_xml: str,
    timestamp: str,
    arr: str,
    parse_fn: Callable[
        [str, TransportModes],
        Union[float, List[float], Tuple[float, List[str], List[str]], None]
    ]
) -> Optional[Union[float, Tuple[float, List[str], List[str]]]]:
    """
    Queries the OJP API for a travel duration between two geographic points.

    This function sends an OJP trip request and uses a customizable parser function
    to extract either a simple duration or full metadata (duration, used modes, stations).

    Args:
        start (Point): Origin in EPSG:4326.
        end (Point): Destination in EPSG:4326.
        mode (str): Transport mode name.
        mode_xml (str): OJP-compatible XML string for the selected travel mode.
        timestamp (str): ISO 8601 timestamp representing the request time.
        arr (str):ISO 8601 timestamp for requested arrival
        parse_fn (Callable): Parser for the XML response; must accept (xml: str, mode: TransportModes)
                             and return one of:
                             - float (duration)
                             - List[float] (durations per leg)
                             - Tuple[float, List[str], List[str]] (full trip metadata)
                             - None (on failure)
    Returns:
        Optional[Union[float, Tuple[float, List[str], List[str]]]]:
            - Duration in minutes (as float)
            - Or (duration, [used_modes], [station_names]) if full_trip is enabled
            - None if no valid response
    
    Raises:
        RateLimitExceededError: If a 429 status code is returned from the OJP API.
    """
    if mode in RENTAL_MODES:
        extension_start, extension_end = "<ojp:Extension>", "</ojp:Extension>"
    else:
        extension_start = extension_end = ""

    logger.debug(f"Sending OJP request: mode={mode}, from={start} to={end}")
    response, status_code = await process_trip_request(
        start, end, mode_xml,
        extension_start=extension_start,
        extension_end=extension_end,
        arr=arr,
        timestamp=timestamp,
        num_results=1
    )

    logger.debug(f"Received status check: {status_code} from OJP.")

    if "429" in status_code:
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    if any(err in status_code for err in ["/ data error!", "/ no valid response!", "/ no trip found!"]):
        logger.warning(f"No valid response from OJP. Reason: {status_code}")
        return None
    if "/ same station!" in status_code:
        logger.debug("Start and end are interpreted as the same station.")
        return 0.0
    
    result = parse_fn(response, mode)
    
    if not result:
        logger.warning("Could not decode duration from OJP response.")
        return None
    
    if isinstance(result, tuple):
        duration, modes, stations = result
        logger.debug(f"Travel time: {duration:.2f} min | Start: {start} | End: {end} | Modes: {modes} | Stations: {stations}")
        return duration, modes, stations
    
    if isinstance(result, list):
        duration = result[0]
    else:
        duration = result
    
    logger.debug(f"Extracted travel time: {duration:.2f} min from start={start} to end={end} using mode={mode}.")
    return duration

class RateLimitExceededError(Exception):
    """Custom exception raised when the API returns a 429 status code."""
    pass