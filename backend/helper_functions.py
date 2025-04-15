#!/usr/bin/env python
# coding: utf-8

from variables import TIMESTAMP, ENDPOINT, ARR, USE_RTREE_SEARCH, WALKING_SPEED, WALKING_NETWORK, USE_MODE_WEIGHTING
from create_send_requests import create_trip_request, send_request, create_location_request
from parse_response import check_and_decode_trip_response, parse_trip_response, decode_duration, parse_location_response
from build_r_tree import find_nearest
from save_and_load_data import get_stored_parking_info, get_stored_closest_rental
from parameter_selection import select_parameters, params_distance_calculation
from shapely.geometry import Point
import osmnx as ox
import networkx as nx
import math

class RateLimitExceededError(Exception):
    pass

def process_trip_request(random_point, destination, mode_xml, extension_start, extension_end, arr=ARR, num_results=1, **kwargs):
    request = create_trip_request(TIMESTAMP, random_point, destination, arr=arr, mode_xml=mode_xml, extension_start=extension_start, extension_end=extension_end, num_results=num_results, **kwargs)
    response = send_request(request, ENDPOINT)
    return check_and_decode_trip_response(response)

def filter_destinations(destinations, public_modes, rtree_indices, G, travel_data, mode):
    """
    Filters rental destinations to ensure they are within max_distance (meters).
    Uses OSMnx walking network if available; otherwise, falls back to Euclidean distance.
    """
    
    mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base = params_distance_calculation(mode)
    best_destination, best_nearest, best_weighted_distance = None, None, float('inf')

    for dest, modes in zip(destinations, public_modes):
        
        nearest, travel_time_walk = get_stored_closest_rental(travel_data, mode, dest, point_isochrones=False)
        if nearest:
            return dest, nearest, travel_time_walk
        
        if USE_RTREE_SEARCH:
            max_distance = base_max_distance * 2
            nearest = find_nearest(rtree_indices, dest.x, dest.y, mode, num_results=1)
            if not nearest:
                continue
            nearest = Point(nearest[0].bbox[:2])
            
            min_distance = nx.shortest_path_length(G, ox.distance.nearest_nodes(G, dest.x, dest.y), ox.distance.nearest_nodes(G, nearest.x, nearest.y), weight='length')
            weighted_distance = distance_weights(modes, min_distance, mode_priority, max_distance, boost_factor, priority_boost_factor, weight_factor_base)
            if not weighted_distance:
                continue
                
            if weighted_distance < best_weighted_distance:
                best_weighted_distance = weighted_distance
                best_destination, best_nearest = dest, nearest
            
            if best_weighted_distance == 0:
                break
        
    if not USE_RTREE_SEARCH or not best_destination:
        radius, restriction_type, poi_filter = select_parameters(mode, rental=True)
        max_distance = base_max_distance * 4  # Less strict maximum distance requirements.
        for dest, modes in zip(destinations, public_modes):
            nearest, _ = location_ojp(dest, 1, False, radius, restriction_type, poi_filter)
            if not nearest:
                continue
            
            nearest = nearest[0]
            
            min_distance = nx.shortest_path_length(G, ox.distance.nearest_nodes(G, dest.x, dest.y), ox.distance.nearest_nodes(G, nearest.x, nearest.y), weight='length')
            weighted_distance = distance_weights(modes, min_distance, mode_priority, max_distance, boost_factor, priority_boost_factor, weight_factor_base)
            if not weighted_distance:
                continue
                
            if weighted_distance < best_weighted_distance:
                best_weighted_distance = weighted_distance
                best_destination, best_nearest = dest, nearest
            
            if best_weighted_distance == 0:
                break
        
    return (best_destination, best_nearest, None) if best_destination else (None, None, None)

def location_ojp(random_point, num_results, include_pt_modes, radius, restriction_type, poi_filter):
    request = create_location_request(TIMESTAMP, random_point, num_results=num_results, include_pt_modes=include_pt_modes, radius=radius, restriction_type=restriction_type, poi_filter=poi_filter)
    response = send_request(request, ENDPOINT)
    
    if response.status_code == 429:
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    if response.status_code != 200:
        print('No valid response from OJP regarding the location information request. Skipping!')
        return None, None
    
    poi_list = parse_location_response(response.text, restriction_type)
    destinations, modes = zip(*[(Point(i['longitude'], i['latitude']), i['modes']) for i in poi_list]) if poi_list else ([], [])
    return destinations, modes

def polygon_filter(polygon, modes, destinations):
    filtered = [(dest, modes[i]) for i, dest in enumerate(destinations) if polygon.contains(dest)]

    return zip(*filtered) if filtered else ([], [])

def process_location_request(random_point, radius, restriction_type, poi_filter, polygon, rtree_indices, mode, G, travel_data, num_results=1, rental=False, include_pt_modes=True, public_transport_modes=None):
    destinations, modes, nearest = [], [], None
    
    if USE_RTREE_SEARCH:
        search_type = 'public-transport' if restriction_type == 'stop' else mode
        
        nearest_stations = find_nearest(rtree_indices, random_point.x, random_point.y, search_type, num_results=num_results)
        destinations = [Point(obj.bbox[:2]) for obj in nearest_stations]
        
        for obj in nearest_stations:
            matching_modes = public_transport_modes[
                (public_transport_modes['longitude'] == obj.bbox[0]) & 
                (public_transport_modes['latitude'] == obj.bbox[1])
            ]

            modes.append(matching_modes['transport_modes'].values[0].split('|') if not matching_modes.empty else [])
    
    destinations, modes = polygon_filter(polygon, modes, destinations)
        
    if not destinations:
        destinations, modes = location_ojp(random_point, num_results, include_pt_modes, radius, restriction_type, poi_filter)
        if not destinations:
            return None, None, None
        
    destinations, modes = polygon_filter(polygon, modes, destinations)
    
    if restriction_type == 'stop' and rental:
        destinations, nearest, modes = filter_destinations(destinations, modes, rtree_indices, G, travel_data, mode)
    
    return destinations, modes, nearest

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
    
    orig, dest = ox.distance.nearest_nodes(G, point1.x, point1.y), ox.distance.nearest_nodes(G, point2.x, point2.y)
    length = nx.shortest_path_length(G, orig, dest, weight='length')
    return math.ceil(length / WALKING_SPEED / 60)

def find_nearest_using_walking_network(idx, x, y, G, mode, polygon):
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
    orig_node = ox.distance.nearest_nodes(G, x, y)
    
    nearest_parking, min_distance = None, float('inf')
    for parking in parking_facilities:
        parking_x, parking_y = parking.bbox[:2]
        if not polygon.contains(Point(parking_x, parking_y)):
            continue
        parking_node = ox.distance.nearest_nodes(G, parking_x, parking_y)
        try:
            distance = nx.shortest_path_length(G, orig_node, parking_node, weight='length')
            if distance < min_distance:
                min_distance, nearest_parking = distance, Point(parking_x, parking_y)
            if min_distance == 0:
                break
        except nx.NetworkXNoPath:
            continue
    return min_distance, nearest_parking

def process_and_get_travel_time(start, end, mode_xml, mode, G):
    """Process trip request and return travel time if successful."""
    
    if WALKING_NETWORK and mode == 'walk':
        return estimated_walking_time(start, end, G)
    
    if mode in ['car_sharing', 'bicycle_rental', 'escooter_rental']:
        extension_start='<ojp:Extension>'
        extension_end='</ojp:Extension>'
    else:
        extension_start=''
        extension_end=''
    
    response, check = process_trip_request(start, end, mode_xml, extension_start=extension_start, extension_end=extension_end, arr=ARR, num_results=1)
    if "429" in check:
        raise RateLimitExceededError("Rate limit exceeded. Exiting loop.")
    if any(err in check for err in ["/ data error!", "/ no valid response!", "/ no trip found!"]):
        print(f'No valid response from OJP. Skipping! Check resulted in: {check}')
        return None
    if '/ same station!' in check:
        return 0
    journeys = parse_trip_response(response, mode)
    duration = decode_duration(journeys) if journeys else []
    if not duration:
        print('No valid travel time from OJP. Skipping!')
        return None
    
    return duration

def distance_weights(transport_modes, min_distance, mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base):
    
    mode_scores = [mode_priority.get(m, 0) for m in transport_modes]
    total_priority_score = sum(mode_scores)
    highest_priority = max(mode_scores, default=0)
    
    count_boost = boost_factor * (len(transport_modes) - 1)
    priority_boost = priority_boost_factor * highest_priority if highest_priority > 1 else 0
    adjusted_max_distance = base_max_distance * (1 + count_boost + priority_boost) if USE_MODE_WEIGHTING else base_max_distance
    
    if min_distance >= adjusted_max_distance:
        return None
    
    weight_factor = 1 + weight_factor_base * (total_priority_score + 0.5 * (len(transport_modes) - 1)) if USE_MODE_WEIGHTING else 1
    weighted_distance = min_distance * weight_factor
    return weighted_distance

def find_valid_nearest_station(idx, destinations, mode, travel_data, G, public_transport_modes, polygon):
    """Find the nearest valid station within the acceptable walking distance.
       Applies a weight to destinations with more transport modes if enabled.
       Also slightly increases max walking distance for better-connected stations.
       Checks if parking data already exists and uses it if available.
    """
    
    mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base = params_distance_calculation(mode)
    
    best_destination, best_nearest, best_weighted_distance = None, None, float('inf')
    
    for dest, modes in zip(destinations, public_transport_modes):
        nearest, travel_time_walk = get_stored_parking_info(travel_data, dest, mode, point_isochrones=False)
        if nearest:
            return dest, nearest, travel_time_walk
        
        min_distance, nearest = find_nearest_using_walking_network(idx, dest.x, dest.y, G, mode, polygon)
        if not nearest:
            continue
            
        weighted_distance = distance_weights(modes, min_distance, mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base)
        if not weighted_distance:
            continue
        
        if weighted_distance < best_weighted_distance:
            best_weighted_distance = weighted_distance
            best_destination, best_nearest = dest, nearest
        
        if best_weighted_distance == 0:
            break
    
    return (best_destination, best_nearest, None) if best_destination else (None, None, None)