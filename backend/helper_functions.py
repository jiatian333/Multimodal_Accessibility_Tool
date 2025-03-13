from variables import *
from create_send_requests import create_trip_request, send_trip_request, create_location_request, send_location_request
from parse_response import check_and_decode_trip_response, parse_trip_response, decode_duration, parse_location_response
from build_r_tree import find_nearest
import time
from shapely.geometry import Point
import osmnx as ox
import networkx as nx

def sleep():
    time.sleep(0.2) # 0.2 seconds
    
def process_trip_request(random_point, destination, mode_xml, arr=ARR, num_results=1, include_stops=False, 
                         include_track_sect=False, include_leg_proj=False, include_turn_desc=False, real_time=True):
    
    request = create_trip_request(TIMESTAMP, random_point, destination, arr=arr, mode_xml=mode_xml, 
                            num_results=num_results, include_stops=include_stops, include_track_sect=include_track_sect, 
                            include_leg_proj=include_leg_proj, include_turn_desc=include_turn_desc, real_time=real_time)
    response = send_trip_request(request, ENDPOINT)
    sleep()
    response, check = check_and_decode_trip_response(response)
    return response, check

def process_location_request(random_point, radius, restriction_type, poi_filter, num_results=1, include_pt_modes=False):
    request = create_location_request(TIMESTAMP, random_point, num_results=num_results, include_pt_modes=include_pt_modes, radius=radius, restriction_type=restriction_type, poi_filter=poi_filter)
    response = send_location_request(request)
    sleep()
    
    #Perhaps add station importance, currently only extracts station with highest porbability. For that: add include_pt_modes, extract it correctly and weigh depending on number of options
    poi_list = parse_location_response(response)
    destination = [Point(i['longitude'], i['latitude']) for i in poi_list]
    
    return destination

def estimated_walking_time(point1: Point, point2: Point, G) -> int:
    """
    Compute estimated walking time (in whole minutes) using the OSM walking network.
    
    Parameters:
    point1 (Point): The first point (longitude, latitude).
    point2 (Point): The second point (longitude, latitude).
    G (networkx.Graph): The walking network graph.
    
    Returns:
    int: Walking time in whole minutes.
    """
    orig = ox.distance.nearest_nodes(G, point1.x, point1.y)
    dest = ox.distance.nearest_nodes(G, point2.x, point2.y)
    length = nx.shortest_path_length(G, orig, dest, weight='length')  # Distance in meters
    return round(length / WALKING_SPEED / 60)  # Convert seconds to whole minutes

def find_nearest_using_walking_network(idx, x, y, G, mode):
    """
    Find the nearest valid station using the OSM walking network for Switzerland.
    
    Parameters:
    idx: Spatial index for station lookup.
    x (float): Longitude of the point.
    y (float): Latitude of the point.
    mode (str): Mode of transport.
    
    Returns:
    Nearest station point or None if not found.
    """
    
    parking_facilities = find_nearest(idx, x, y, mode, num_results=2)
    min_distance = float('inf')
    nearest_parking = None
    
    orig_node = ox.distance.nearest_nodes(G, x, y)
    
    for parking_facility in parking_facilities:
        parking_x, parking_y = parking_facility.bbox[0], parking_facility.bbox[1]
        
        # Get the nearest node in the network for the parking facility
        parking_node = ox.distance.nearest_nodes(G, parking_x, parking_y)
        
        try:
            distance = nx.shortest_path_length(G, orig_node, parking_node, weight='length')
            if distance < min_distance:
                min_distance = distance
                nearest_parking = Point(parking_x, parking_y)
        except nx.NetworkXNoPath:
            continue  # Skip if no path exists
    
    return min_distance, nearest_parking
    

def find_valid_nearest_station(idx, destinations, mode, travel_data, G, max_distance=700):
    """Find the nearest valid station within the acceptable walking distance.
       Also checks if parking data already exists and uses it if available."""
    
    for dest in destinations:
        # Check if parking info is already stored
        if mode in ['cycle', 'bicycle_rental', 'escooter_rental'] and (dest.x, dest.y) in travel_data['bike-parking']:
            print('Retrieving stored parking information.')
            return dest, travel_data['bike-parking'][dest]['parking'], travel_data['bike-parking'][dest]['travel_time']
        
        elif mode in ['self-drive-car', 'car_sharing'] and (dest.x, dest.y) in travel_data['car-parking']:
            print('Retrieving stored parking information.')
            return dest, travel_data['car-parking'][dest]['parking'], travel_data['car-parking'][dest]['travel_time']

        # Find nearest station
        min_distance, nearest = find_nearest_using_walking_network(idx, dest.x, dest.y, G, mode)  # Use walking network
        if not nearest:
            continue

        if min_distance < max_distance:
            return dest, nearest, None  # No pre-stored walking time, must compute it
    print('No valid destination found. Skipping!')
    return None, None, None  # No valid destination found

def process_and_get_travel_time(start, end, mode_xml, mode, G):
    """Process trip request and return travel time if successful."""
    if WALKING_NETWORK and mode == 'walk':
        print('Using network instead of OJP to determine walking travel time')
        travel_time = estimated_walking_time(start, end, G)
        print(f'Estimated walking time from {start} to {end}: {travel_time} minutes')
        return travel_time
    
    response, check = process_trip_request(start, end, mode_xml, arr=ARR, num_results=1)
    if "/ data error!" in check or "/ no valid response!" in check or '/ no trip found!' in check:
        print('No valid response from OJP. Skipping!')
        return None  # Invalid response, return None
    journeys = parse_trip_response(response)
    duration = [journey['duration'] for journey in journeys]
    if not duration:
        print('No valid travel time from OJP. Skipping!')
        return None
    duration = decode_duration(duration)
    print(f'Travel time from {start} to {end} using {mode} is {duration} minutes!')
    return duration