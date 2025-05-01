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
- `process_and_get_travel_time`: Orchestrates OJP or walking network duration estimates.

Exceptions:
-----------
- `RateLimitExceededError`: Raised when OJP returns HTTP 429.

Usage:
------
    from app.utils.ojp_helpers import (
        process_trip_request,
        location_ojp,
        process_and_get_travel_time,
        RateLimitExceededError
    )
"""


import logging
from typing import Tuple, List, Optional

from shapely.geometry import Point

from app.core.config import ENDPOINT
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

class RateLimitExceededError(Exception):
    """Custom exception raised when the API returns a 429 status code."""
    pass