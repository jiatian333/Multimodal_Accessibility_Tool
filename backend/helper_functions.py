from variables import *
from create_send_requests import create_trip_request, send_trip_request, create_location_request, send_location_request
from parse_response import check_and_decode_trip_response, parse_trip_response, decode_duration, parse_location_response
from build_r_tree import find_nearest
from save_and_load_data import get_stored_parking_info
import time
from shapely.geometry import Point
import osmnx as ox
import networkx as nx
import math

class RateLimitExceededError(Exception):
    pass

def sleep():
    time.sleep(0.2) # 0.2 seconds
    
def process_trip_request(random_point, destination, mode_xml, arr=ARR, num_results=1, include_stops=False, 
                         include_track_sect=False, include_leg_proj=False, include_turn_desc=False, real_time=True):
    
    request = create_trip_request(TIMESTAMP, random_point, destination, arr=ARR, mode_xml=mode_xml, 
                            num_results=num_results, include_stops=include_stops, include_track_sect=include_track_sect, 
                            include_leg_proj=include_leg_proj, include_turn_desc=include_turn_desc, real_time=real_time)
    response = send_trip_request(request, ENDPOINT)
    sleep()
    response, check = check_and_decode_trip_response(response)
    return response, check

def process_location_request(random_point, radius, restriction_type, poi_filter, polygon, num_results=1, include_pt_modes=True):
    request = create_location_request(TIMESTAMP, random_point, num_results=num_results, include_pt_modes=include_pt_modes, radius=radius, restriction_type=restriction_type, poi_filter=poi_filter)
    response = send_location_request(request)
    sleep()
    if response.status_code==429:
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    elif response.status_code!=200:
        print('No valid response from OJP regarding the location information request. Skipping!')
        return None, None
        
    poi_list = parse_location_response(response.text, restriction_type)
    destination = [Point(i['longitude'], i['latitude']) for i in poi_list]
    modes = [i['modes'] for i in poi_list]
    
    destination = [dest for dest in destination if polygon.contains(dest)]
    modes = [modes[i] for i in range(len(destination)) if polygon.contains(destination[i])]
    
    return destination, modes

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
    return math.ceil(length / WALKING_SPEED / 60)  # Convert seconds to whole minutes, rounding up to prevent too optimistic results

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
            if min_distance==0:
                break
        except nx.NetworkXNoPath:
            continue  # Skip if no path exists
    
    return min_distance, nearest_parking

def find_valid_nearest_station(idx, destinations, mode, travel_data, G, public_transport_modes):
    """Find the nearest valid station within the acceptable walking distance.
       Applies a weight to destinations with more transport modes if enabled.
       Also slightly increases max walking distance for better-connected stations.
       Also checks if parking data already exists and uses it if available.
    """
    
    # Mode priority mapping (higher value = higher priority)
    mode_priority = {
        'rail': 2,
        'tram': 1,
        'bus': 0,
        'suburbanRail': 1,
        'urbanRail': 1,
        'metro': 1,
        'underground': 1,
        'coach': 0,
        'water': 1,
        'air': 2,
        'telecabin': 0,
        'funicular': 0,
        'taxi': 1,
        'selfDrive': 1,
        'unknown': 0
    }
    
    best_destination = None
    best_nearest = None
    best_weighted_distance = float('inf')

    for i, dest in enumerate(destinations):
        
        nearest, travel_time_walk = get_stored_parking_info(travel_data, dest, mode, point_isochrones=False)
        if nearest:
            return dest, nearest, travel_time_walk

        # Find nearest station using the walking network
        min_distance, nearest = find_nearest_using_walking_network(idx, dest.x, dest.y, G, mode)
        if not nearest:
            continue

        # Calculate the total priority score for this destination
        mode_scores = [mode_priority[m] for m in public_transport_modes[i] if m in mode_priority]
        total_priority_score = sum(mode_scores) if mode_scores else 0

        # Base max distance per mode
        base_max_distance = 300 if mode in ['car_sharing', 'self-drive-car'] else 200

        # Calculate the boost based on the number of modes (count boost)
        boost_factor = 0.05  # 5% extra per additional mode
        count_boost = boost_factor * (len(public_transport_modes[i]) - 1)

        # Determine the highest priority among available modes
        highest_priority = max([mode_priority.get(m, 0) for m in public_transport_modes[i]] or [0])

        # Only add a priority boost if the highest priority is above 1 (i.e., not just bus)
        priority_boost = 0.1 * highest_priority

        # Combine both boosts to adjust the maximum walking distance
        adjusted_max_distance = base_max_distance * (1 + count_boost + priority_boost) if USE_MODE_WEIGHTING else base_max_distance

        if min_distance >= adjusted_max_distance:
            continue  # Skip if walking distance is too long

        # Apply weighting based on priority score (higher priority modes should shorten the distance more)
        # Reduced weight factor effect (smaller adjustments)
        weight_factor = 1 + 0.05 * (total_priority_score + 0.5 * (len(public_transport_modes[i]) - 1)) if USE_MODE_WEIGHTING else 1
        weighted_distance = min_distance * weight_factor

        # Choose the best station (smallest weighted distance)
        if weighted_distance < best_weighted_distance:
            best_weighted_distance = weighted_distance
            best_destination = dest
            best_nearest = nearest
        if best_weighted_distance==0:
            break

    if best_destination:
        return best_destination, best_nearest, None  # No pre-stored walking time, must compute it

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
    
    if "429" in check:  # Check for rate-limiting error
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    
    if "/ data error!" in check or "/ no valid response!" in check or '/ no trip found!' in check:
        print(f'No valid response from OJP. Skipping! Check resulted in: {check}')
        return None  # Invalid response, return None
    journeys = parse_trip_response(response)
    duration = [journey['duration'] for journey in journeys]
    if not duration:
        print('No valid travel time from OJP. Skipping!')
        return None
    duration = decode_duration(duration)
    print(f'Travel time from {start} to {end} using {mode} is {duration} minutes!')
    return duration