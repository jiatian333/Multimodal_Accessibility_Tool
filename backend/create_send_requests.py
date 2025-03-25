import requests
from variables import *

def create_trip_request(timestamp, origin, destination, mode_xml, arr=ARR, real_time=True,
                            num_results=2, include_stops=False, include_track_sect=False, include_leg_proj=False, 
                            include_turn_desc=False):
    """
    Constructs an OJP TripRequest XML.
    """
    # Read the XML template from file
    with open("templates/travel_times10.xml", "r", encoding="utf-8") as file:
        xml_request = file.read()

    xml_request = xml_request.replace("${timestamp}", timestamp)
    xml_request = xml_request.replace("${origin_lat}", str(origin.y))
    xml_request = xml_request.replace("${destination_lat}", str(destination.y))
    xml_request = xml_request.replace("${origin_lon}", str(origin.x))
    xml_request = xml_request.replace("${destination_lon}", str(destination.x))
    xml_request = xml_request.replace("${arr}", arr)
    xml_request = xml_request.replace("${num_results}", str(num_results))
    xml_request = xml_request.replace("${include_track_sect}", str(include_track_sect).lower())
    xml_request = xml_request.replace("${include_stops}", str(include_stops).lower())
    xml_request = xml_request.replace("${include_leg_proj}", str(include_leg_proj).lower())
    xml_request = xml_request.replace("${include_turn_desc}", str(include_turn_desc).lower())
    xml_request = xml_request.replace("${mode_xml}", mode_xml)
    xml_request = xml_request.replace("${real_time}", str(real_time).lower())

    return xml_request

def send_trip_request(xml_request, endpoint):
    """
    Sends the OJP TripRequest to the server.
    """
    headers = {'Authorization':  f"Bearer {KEY}", 
               'Content-Type': 'application/xml; charset=utf-8'}
    response = requests.post(endpoint, data=xml_request.encode('utf-8'), headers=headers, allow_redirects=True)
    return response

def create_location_request(timestamp, origin, restriction_type="stop", num_results=5, include_pt_modes=True, radius=500, poi_filter=''):
    """
    Constructs an OJP LocationInformationRequest XML.
    """
    with open("templates/location_search10.xml", "r", encoding="utf-8") as file:
        xml_request = file.read()

    xml_request = xml_request.replace("${timestamp}", timestamp)
    xml_request = xml_request.replace("${origin_lon}", str(origin.x))
    xml_request = xml_request.replace("${origin_lat}", str(origin.y))
    xml_request = xml_request.replace("${restriction_type}", restriction_type)
    xml_request = xml_request.replace("${number_of_results}", str(num_results))
    xml_request = xml_request.replace("${include_pt_modes}", str(include_pt_modes).lower())
    xml_request = xml_request.replace("${radius}", str(radius))
    xml_request = xml_request.replace("${poi_filter}", poi_filter)

    return xml_request

def send_location_request(xml_request):
    """
    Sends the OJP LocationInformationRequest and returns the response.
    """
    headers = {'Authorization':  f"Bearer {KEY}", 
               'Content-Type': 'application/xml; charset=utf-8'}
    response = requests.post(ENDPOINT, data=xml_request, headers=headers)
    
    return response
