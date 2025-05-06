"""
OJP API Response Parsing Utilities

This module provides tools to parse XML responses returned from the OJP API,
specifically for journey planning and location search endpoints.

Functions:
----------
- check_trip_response(...): Validates the XML trip response.
- parse_trip_response(...): Extracts duration strings from trip legs.
- decode_duration(...): Converts ISO 8601 duration into minutes.
- parse_location_response(...): Extracts location information including coordinates and transport modes.

Returns:
--------
Structured data such as durations (ISO strings), travel times (float in minutes), or POI coordinates (dict).
"""


import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Union, Optional

from app.core.config import TransportModes

def check_trip_response(response_text: str, status: int) -> str:
    """
    Validates and decodes a raw XML trip response from the OJP API.

    Args:
        response_text (str): Response XML from the OJP API.
        status (int): Status code of the OJP response. 

    Returns:
        str: 
            - Status summary (including warnings if data is invalid).
    """
    status_str = str(status)
    if status != 200:
        status_str += " / data error!"
    elif not any(tag in response_text for tag in ["ServiceDelivery", "trips"]):
        status_str += " / no valid response!"
    elif "<siri:ErrorText>TRIP_NOTRIPFOUND</siri:ErrorText>" in response_text:
        status_str += " / no trip found!"
    elif "<siri:ErrorText>TRIP_ORIGINDESTINATIONIDENTICAL</siri:ErrorText>" in response_text:
        status_str += " / same station!"

    return status_str

def parse_trip_response(
    response_xml: str,
    mode: TransportModes,
    full_trip: bool = False
) -> Union[List[str], List[float]]:
    """
    Parses an OJP TripResponse XML and extracts durations for the requested transport mode.
    
    When `full_trip` is enabled, also includes durations of adjacent walking legs and returns
    the total duration in minutes (decoded from ISO 8601 format).

    Args:
        response_xml (str): UTF-8 decoded XML response string from OJP API.
        mode (TransportModes): Target transport mode (e.g., 'self-drive-car').
        full_trip (bool): If True, also includes durations of adjacent walk legs 
                          and returns decoded minutes. If False (default), returns 
                          only mode-specific ISO 8601 duration strings.

    Returns:
        Union[List[str], List[float]]:
            - If full_trip is False: List of ISO 8601 duration strings.
            - If full_trip is True: List of total durations in float minutes.
    """
    namespaces = {
        "siri": "http://www.siri.org.uk/siri",
        "ojp": "http://www.vdv.de/ojp"
    }
    
    def extract_adjacent_walk_duration(leg: ET.Element) -> Optional[float]:
        """
        Extracts duration in minutes for a leg if it is a walking segment.

        Args:
            leg (ET.Element): The XML element representing a trip leg.

        Returns:
            Optional[float]: Duration in minutes if the leg is a walking leg, otherwise None.
        """
        neighbor_mode = leg.findtext(".//ojp:IndividualMode", default="", namespaces=namespaces)
        if neighbor_mode.lower() == "walk":
            duration_str = leg.findtext(".//ojp:Duration", default=None, namespaces=namespaces)
            if duration_str:
                return decode_duration([duration_str])
        return None

    root = ET.fromstring(response_xml)
    results = []
    default = None if full_trip else 'Unknown'

    for trip_result in root.findall(".//ojp:TripResult", namespaces):
        trip_legs = trip_result.findall(".//ojp:TripLeg", namespaces)

        for i, trip_leg in enumerate(trip_legs):
            mode_element = trip_leg.find(".//ojp:IndividualMode", namespaces)
            if mode_element is not None and mode_element.text == mode:
                duration = trip_leg.findtext(".//ojp:Duration", default=default, namespaces=namespaces)
                
                if not full_trip:
                    results.append(duration)
                    continue

                durations = []
                if duration:
                    main_duration = decode_duration([duration])
                    if main_duration:
                        durations.append(main_duration)

                if i > 0:
                    prev_duration = extract_adjacent_walk_duration(trip_legs[i - 1])
                    if prev_duration:
                        durations.append(prev_duration)

                if i < len(trip_legs) - 1:
                    next_duration = extract_adjacent_walk_duration(trip_legs[i + 1])
                    if next_duration:
                        durations.append(next_duration)

                if durations:
                    results.append(sum(durations))
                break

    return results

def decode_duration(duration: List[str]) -> Optional[float]:
    """
    Decodes an ISO 8601 duration string (first entry in list) into total minutes.

    Args:
        duration (List[str]): List of ISO 8601 durations (e.g., ['PT1H20M']).

    Returns:
        Optional[float]: Total travel time in minutes, or None if invalid.
    """
    if not duration:
        return None
    
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration[0])
    if not match:
        return None

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 60 + minutes + seconds / 60.0

def parse_location_response(response_xml: str, restriction_type: str) -> List[Dict[str, Union[float, List[Optional[str]]]]]:
    """
    Parses an OJP LocationInformation XML response and extracts POIs.

    Args:
        response_xml (str): XML string returned from a location search.
        restriction_type (str): Type of location request ('stop', 'poi').

    Returns:
        List[Dict]: 
            - longitude: float
            - latitude: float
            - modes: list of modes (only if restriction_type is "stop")
    """
    namespaces = {
        "siri": "http://www.siri.org.uk/siri",
        "ojp": "http://www.vdv.de/ojp"
    }

    root = ET.fromstring(response_xml)
    poi_list = []

    for location in root.findall(".//ojp:OJPLocationInformationDelivery/ojp:Location", namespaces):
        poi_lon = location.find(".//ojp:GeoPosition/siri:Longitude", namespaces)
        poi_lat = location.find(".//ojp:GeoPosition/siri:Latitude", namespaces)

        if poi_lon is None or poi_lat is None:
            continue

        poi_info = {
            "longitude": float(poi_lon.text),
            "latitude": float(poi_lat.text),
            "modes": []
        }

        if restriction_type == "stop":
            modes = [
                mode.text.strip()
                for mode in location.findall(".//ojp:Mode/ojp:PtMode", namespaces)
                if mode.text
            ]
            poi_info["modes"] = modes

        poi_list.append(poi_info)

    return poi_list