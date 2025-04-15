#!/usr/bin/env python
# coding: utf-8

from variables import TEMPLATES_PATH, KEY
import requests


def create_trip_request(timestamp, origin, destination, mode_xml, arr, extension_start='', extension_end='', real_time=True,
                        num_results=2, include_stops=False, include_track_sect=False, include_leg_proj=False, 
                        include_turn_desc=False):
    """
    Constructs an OJP TripRequest XML.
    """
    with open(TEMPLATES_PATH+"travel_times10.xml", "r", encoding="utf-8") as file:
        xml_request = file.read()

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
        "${extension_start}": extension_start,
        "${extension_end}": extension_end
    }
    
    for key, value in replacements.items():
        xml_request = xml_request.replace(key, value)

    return xml_request

def create_location_request(timestamp, origin, restriction_type="stop", num_results=5, include_pt_modes=True, radius=500, poi_filter=''):
    """
    Constructs an OJP LocationInformationRequest XML.
    """
    with open(TEMPLATES_PATH+"location_search10.xml", "r", encoding="utf-8") as file:
        xml_request = file.read()

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

    for key, value in replacements.items():
        xml_request = xml_request.replace(key, value)

    return xml_request

def send_request(xml_request, endpoint):
    """
    Sends an XML request to the server.
    
    Args:
        xml_request (str): The XML request string.
        endpoint (str): The URL endpoint (default: ENDPOINT from variables).

    Returns:
        Response object from the request.
    """
    headers = {
        'Authorization': f"Bearer {KEY}",
        'Content-Type': 'application/xml; charset=utf-8'
    }
    return requests.post(endpoint, data=xml_request.encode('utf-8'), headers=headers, allow_redirects=True)