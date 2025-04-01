import xml.etree.ElementTree as ET
import re

def check_and_decode_trip_response(response_xml):
    response_text = response_xml.content.decode('utf-8')
    check = f'{str(response_xml.status_code)} {str(response_xml.reason)}'
    
    if response_xml.status_code != 200:
        check += ' / data error!'
    elif not any(tag in response_text for tag in ['ServiceDelivery', 'trips']):
        check += ' / no valid response!'
    elif '<siri:ErrorText>TRIP_NOTRIPFOUND</siri:ErrorText>' in response_text:
        check += '/ no trip found!'
    
    return response_text, check

def parse_trip_response(response_xml):
    """
    Parses the OJP TripResponse XML to extract journey details.
    """
    root = ET.fromstring(response_xml)
    namespaces = {
        'siri': "http://www.siri.org.uk/siri",
        'ojp': "http://www.vdv.de/ojp"
    }
    journeys = []
    
    for journey in root.findall(".//ojp:TripResult", namespaces):
        trip_info = {
            'duration': journey.findtext(".//ojp:Duration", default="Unknown", namespaces=namespaces)
        }
        
        journeys.append(trip_info)
    
    return journeys

def decode_duration(duration):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration[0])
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0

    total_minutes = hours * 60 + minutes + seconds / 60
    return total_minutes

def parse_location_response(response_xml, restriction_type):
    """
    Parses the OJP response and extracts nearest POI coordinates along with probability.
    """
    root = ET.fromstring(response_xml)
    namespaces = {
        'siri': "http://www.siri.org.uk/siri",
        'ojp': "http://www.vdv.de/ojp"
    }

    poi_list = []

    # Select only direct child <ojp:Location> inside <ojp:OJPLocationInformationDelivery>
    for location in root.findall(".//ojp:OJPLocationInformationDelivery/ojp:Location", namespaces):
        poi_info = {}

        # Extract coordinates
        poi_lon = location.find(".//ojp:GeoPosition/siri:Longitude", namespaces)
        poi_lat = location.find(".//ojp:GeoPosition/siri:Latitude", namespaces)
        poi_info['longitude'] = float(poi_lon.text) if poi_lon is not None else None
        poi_info['latitude'] = float(poi_lat.text) if poi_lat is not None else None
        
        # If restriction_type is 'stop', extract modes for this specific location
        if restriction_type == 'stop':
            modes = []
            for mode in location.findall(".//ojp:Mode/ojp:PtMode", namespaces):  # Only within this location
                if mode.text:
                    modes.append(mode.text.strip())
            poi_info['modes'] = modes 
        else:
            poi_info['modes'] = None

        poi_list.append(poi_info)

    return poi_list