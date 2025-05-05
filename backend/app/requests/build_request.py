"""
OJP Request Builder for Travel Time and Location Queries

This module constructs and sends XML-based requests to the OJP (Open Journey Planning) API. It supports:
- Journey planning (TripRequest)
- Location search (LocationInformationRequest)

It also includes logic to:
- Enforce a global concurrency limit using a semaphore
- Apply rate limiting to control total requests per time window

Core Functions:
---------------
- create_trip_request(...): Builds a journey planning XML request.
- create_location_request(...): Builds a location search XML request.
- send_request(...): Sends an XML request to the OJP API with concurrency and rate limit protection.
- enforce_rate_limit(...): Internal helper to throttle request rate based on configured limits.

Dependencies:
-------------
- requests: Synchronous HTTP POST handling
- asyncio: For concurrency management and throttling
- shapely.geometry.Point: For geographic inputs
- app.core.config: Provides API credentials, template paths, and throttling constants

Template Requirements:
----------------------
Template XML files must be located under `TEMPLATES_PATH`, and include placeholders
like `${origin_lat}`, `${mode_xml}`, etc. which are replaced dynamically.
"""

import asyncio
import logging
import os
import time
import requests  
from collections import deque  
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from shapely.geometry import Point

from app.core.config import (
    TEMPLATES_PATH, KEY, OJP_SEMAPHORE,
    RATE_LIMIT, RATE_PERIOD, RateLock
)

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor()
call_timestamps = deque()
MIN_SPACING = RATE_PERIOD / RATE_LIMIT + 0.05
last_request_time = time.monotonic()

def create_trip_request(
    timestamp: str,
    origin: Point,
    destination: Point,
    mode_xml: str,
    arr: str,
    extension_start: Optional[str] = '',
    extension_end: Optional[str] = '',
    real_time: bool = True,
    num_results: int = 2,
    include_stops: bool = False,
    include_track_sect: bool = False,
    include_leg_proj: bool = False,
    include_turn_desc: bool = False
) -> str:
    """
    Constructs a journey planning TripRequest XML using a predefined template.

    Args:
        timestamp (str): Timestamp of the request (ISO 8601 format).
        origin (Point): Origin location as a Shapely Point.
        destination (Point): Destination location as a Shapely Point.
        mode_xml (str): XML string describing the travel mode.
        arr (str): Desired arrival time (ISO 8601 format).
        extension_start (str): Optional XML extension block for start.
        extension_end (str): Optional XML extension block for end.
        real_time (bool): Whether to use real-time data.
        num_results (int): Number of journey results to request.
        include_stops (bool): Whether to include stops.
        include_track_sect (bool): Whether to include track sections.
        include_leg_proj (bool): Whether to include leg projection.
        include_turn_desc (bool): Whether to include turn-by-turn description.

    Returns:
        str: The final XML string ready for request submission.
    """
    template_path = os.path.join(TEMPLATES_PATH, "travel_times.xml")
    try:
        with open(template_path, "r", encoding="utf-8") as file:
            xml_request = file.read()
    except FileNotFoundError:
        logger.error(f"Missing template: {template_path}")
        raise RuntimeError(f"Missing template: {template_path}")

    replacements = {
        "${timestamp}": timestamp,
        "${origin_lat}": str(origin.y),
        "${destination_lat}": str(destination.y),
        "${origin_lon}": str(origin.x),
        "${destination_lon}": str(destination.x),
        "${arr}": arr,
        "${num_results}": str(num_results),
        "${include_track_sect}": str(include_track_sect).lower(),
        "${include_stops}": str(include_stops).lower(),
        "${include_leg_proj}": str(include_leg_proj).lower(),
        "${include_turn_desc}": str(include_turn_desc).lower(),
        "${mode_xml}": mode_xml,
        "${real_time}": str(real_time).lower(),
        "${extension_start}": extension_start or "",
        "${extension_end}": extension_end or ""
    }

    for placeholder, value in replacements.items():
        xml_request = xml_request.replace(placeholder, value)

    return xml_request


def create_location_request(
    timestamp: str,
    origin: Point,
    restriction_type: str = "stop",
    num_results: int = 5,
    include_pt_modes: bool = True,
    radius: int = 500,
    poi_filter: str = ""
) -> str:
    """
    Constructs a location search request (LocationInformationRequest).

    Args:
        timestamp (str): Timestamp of the request (ISO 8601 format).
        origin (Point): Center point of location query.
        restriction_type (str): Type of result to return (e.g., 'stop', 'poi').
        num_results (int): Number of results to return.
        include_pt_modes (bool): Whether to include public transport modes.
        radius (int): Search radius around the origin (in meters).
        poi_filter (str): Optional point of interest filter for POIs.

    Returns:
        str: XML request string ready to be sent to the OJP API.
    """
    template_path = os.path.join(TEMPLATES_PATH, "location_search.xml")
    try: 
        with open(template_path, "r", encoding="utf-8") as file:
            xml_request = file.read()
    except FileNotFoundError:
        logger.error(f"Missing template: {template_path}")
        raise RuntimeError(f"Missing template: {template_path}")

    replacements = {
        "${timestamp}": timestamp,
        "${origin_lon}": str(origin.x),
        "${origin_lat}": str(origin.y),
        "${restriction_type}": restriction_type,
        "${number_of_results}": str(num_results),
        "${include_pt_modes}": str(include_pt_modes).lower(),
        "${radius}": str(radius),
        "${poi_filter}": poi_filter
    }

    for placeholder, value in replacements.items():
        xml_request = xml_request.replace(placeholder, value)

    return xml_request

'''last_reset_time = time.monotonic()

async def enforce_rate_limit():
    """
    Enforces bursty rate limit: allows up to RATE_LIMIT requests quickly,
    then pauses for RATE_PERIOD before allowing another burst.
    """
    global last_reset_time

    async with RateLock:
        now = time.monotonic()

        # Initialize or reset if window expired
        if now - last_reset_time > RATE_PERIOD:
            call_timestamps.clear()
            last_reset_time = now

        if len(call_timestamps) >= RATE_LIMIT:
            wait_time = RATE_PERIOD - (now - last_reset_time)
            await asyncio.sleep(wait_time)

            # Reset after waiting
            now = time.monotonic()
            call_timestamps.clear()
            last_reset_time = now

        call_timestamps.append(now)'''

'''async def enforce_rate_limit():
    """
    Asynchronously enforces a global request rate limit for OJP API access.

    It tracks recent request timestamps and delays further requests if the number
    of requests within the defined `RATE_PERIOD` exceeds the configured `RATE_LIMIT`.

    This ensures compliance with external API quotas.

    Behavior:
        - If the current request window is full, pauses execution until one slot clears.
        - Uses `RateLock` to synchronize across concurrent callers.

    Raises:
        asyncio.CancelledError: If the coroutine is cancelled during sleep.
    """
    async with RateLock:
        now = time.monotonic()
        while call_timestamps and now - call_timestamps[0] > RATE_PERIOD:
            call_timestamps.popleft()

        if len(call_timestamps) >= RATE_LIMIT:
            wait_time = RATE_PERIOD - (now - call_timestamps[0])
            await asyncio.sleep(wait_time)
        
        call_timestamps.append(time.monotonic())'''

async def enforce_rate_limit():
    """
    Ensures that each request is spaced by at least MIN_SPACING seconds.
    Enforces spacing across concurrent tasks using a global RateLock.
    """
    global last_request_time

    async with RateLock:
        now = time.monotonic()
        wait_time = 0.8 - (now - last_request_time)

        if wait_time > 0:
            await asyncio.sleep(wait_time)

        last_request_time = time.monotonic()

async def send_request(xml_request: str, endpoint: str) -> Tuple[str, int]:
    """
    Sends an XML-based OJP request asynchronously to the given API endpoint.

    This function ensures non-blocking execution by running the synchronous
    HTTP request inside a thread pool. It enforces request concurrency limits 
    via a global `OJP_SEMAPHORE` and also caps total requests over a rolling 
    time window via a rate limiter (`enforce_rate_limit`).

    Args:
        xml_request (str): Fully rendered XML payload (TripRequest or LocationInformationRequest).
        endpoint (str): Target URL of the OJP API.

    Returns:
        Tuple[str, int]: A tuple of (response body as string, HTTP status code).

    Raises:
        requests.RequestException: If the POST request fails internally.
    """
    def blocking_post():
        """
        Synchronously sends the XML payload via POST with proper headers

        Returns:
            Tuple[str, int]: A tuple of (response body as string, HTTP status code).
        """
        headers = {
            'Authorization': f"Bearer {KEY}",
            'Content-Type': 'application/xml; charset=utf-8'
        }
        response = requests.post(endpoint, data=xml_request.encode('utf-8'), headers=headers)
        return response.text, response.status_code
    
    await enforce_rate_limit()
    
    async with OJP_SEMAPHORE:
        return await asyncio.get_event_loop().run_in_executor(executor, blocking_post)