from variables import *
from helper_functions import process_location_request, process_and_get_travel_time, find_valid_nearest_station, find_nearest_using_walking_network, RateLimitExceededError
from parameter_selection import select_parameters, mode_selection
from save_and_load_data import store_parking, get_stored_parking_info, store_travel_time, store_point_travel_time, store_rental_station_info, store_closest_rental, get_stored_closest_rental

def network_travel_times(travel_data, random_points, G, polygon, idx, public_transport_stations):
    successful_points = 0
    already_processed_points=0
    mode_data = travel_data[MODE]  # Cache for efficiency
    rental_modes = {'escooter_rental', 'bicycle_rental', 'car_sharing'}
    rental = (MODE in rental_modes)
    
    for i, random_point in enumerate(random_points):
        print(f'\n----------------------------------------------------------\n') if i else None
        
        if random_point in mode_data["isochrones"]:
            print(f"Skipping point: {random_point}, already processed.")
            already_processed_points+=1
            continue
        
        try: 
            travel_time = 0
            rental_stored = False
            current_point = random_point
            
            if rental:
                radius, restriction_type, poi_filter = select_parameters(rental=True)
                rental_station, _, _ = process_location_request(random_point, radius, restriction_type, poi_filter, polygon, idx, MODE, G, travel_data, num_results=1, rental=rental, public_transport_modes=public_transport_stations)
                
                if not rental_station:
                    print('No valid rental station found. Skipping!')
                    continue
                
                rental_station = rental_station[0]
                rental_info = mode_data['rental'].get(rental_station, {})
                
                if "travel_time" in rental_info and "nearest" in rental_info:
                    travel_time_mode = rental_info["travel_time"]
                    destination = [rental_info['nearest']]
                    nearest, travel_time_walk = get_stored_closest_rental(travel_data, mode, destination, point_isochrones=False)
                    print('Stored Rental Information found and retrieved')
                    rental_stored = True
                else:
                    rental_stored = False  # Recompute if incomplete data exists
                    current_point = rental_station
            
            if not rental_stored:
                radius, restriction_type, poi_filter = select_parameters()
                num_results = 8 if MODE != 'walk' else 1
                destination, stored, nearest = process_location_request(current_point, radius, restriction_type, poi_filter, polygon, idx, MODE, G, travel_data, num_results=num_results, rental=rental, public_transport_modes=public_transport_stations)
                
                if not destination:
                    print('No valid destination found. Skipping!')
                    continue
                
                mode = {'car_sharing': 'self-drive-car', 'bicycle_rental': 'cycle'}.get(MODE, MODE)
                mode_xml = mode_selection(mode)
            
            if MODE != 'walk':
                if not rental:
                    destination, nearest, travel_time_walk = find_valid_nearest_station(idx, destination, MODE, travel_data, G, public_transport_modes=stored, polygon=polygon)
                else:
                    travel_time_walk = stored
                
                if not nearest:
                    continue  # Skip to the next point if no valid station is found
                
                if not rental_stored:
                    if (travel_time_mode := process_and_get_travel_time(current_point, nearest, mode_xml, mode, G)) is None:
                        continue  # Skip to the next point if trip request failed
                    if rental:
                        if (travel_time := process_and_get_travel_time(random_point, rental_station, mode_selection('walk'), 'walk', G)) is None:
                            continue
                
                if travel_time_walk is None:
                    if (travel_time_walk := process_and_get_travel_time(nearest, destination, mode_selection('walk'), 'walk', G)) is None:
                        continue  # Skip to the next point if trip request failed
                    if not rental:
                        travel_data = store_parking(MODE, destination, nearest, travel_data, travel_time_walk)

                if not rental_stored and rental:
                    travel_data = store_rental_station_info(rental_station, destination, travel_time_mode, MODE, travel_data)
                    travel_data = store_closest_rental(travel_data, MODE, destination, nearest, travel_time_walk)
                    
                travel_time += travel_time_mode + travel_time_walk
            else:
                destination = destination[0]
                if (travel_time := process_and_get_travel_time(current_point, destination, mode_xml, MODE, G)) is None:
                    continue  # Skip to the next point if trip request failed
                
            travel_data = store_travel_time(MODE, random_point, destination, travel_time, travel_data)
            successful_points+=1
            
        except RateLimitExceededError as e:
            print(f"Rate limit exceeded, exiting loop: {e}. Isochrones will still be generated using the existing information but may appear incomplete/contain atrifacts")
            break  # Exit the loop if rate limit is exceeded
    
    print(f"Successfully processed and stored {successful_points} out of {len(random_points)} points.")
    print(f'{already_processed_points} points were already stored in the database.')
        
    return travel_data
    
    
def point_travel_times(travel_data, center, points, idx, G, polygon, public_transport_modes, mode=MODE):
    """ Computes and stores travel times from a center to multiple points. """
    
    travel_times, valid_points = [], []
    nearest, travel_time_start = None, 0
    rental_modes = {'escooter_rental', 'bicycle_rental', 'car_sharing'}
    rental = (mode in rental_modes)
    
    try: 
        if mode != 'walk':
            nearest, travel_time_start = get_stored_parking_info(travel_data, center, mode, point_isochrones=True)
            
            if not nearest:
                if rental:
                    radius, restriction_type, poi_filter = select_parameters(rental=rental)
                    nearest, _, _ = process_location_request(center, radius, restriction_type, poi_filter, polygon, idx, mode, G, travel_data, num_results=1, rental=rental, include_pt_modes=False, public_transport_modes=public_transport_modes)
                    if not nearest: 
                        print(f'No valid parking/rental found near point {center}. Not possible to determine point isochrones')
                        return None
                    nearest = nearest[0]
                else:
                    _, nearest = find_nearest_using_walking_network(idx, center.x, center.y, G, mode, polygon)
                
                if not nearest:
                    print(f'No valid parking/rental found near point {center}. Not possible to determine point isochrones')
                    return None
                
                # Determine travel time walk between nearest and center, assume parking is available at end point
                if (travel_time_start := process_and_get_travel_time(center, nearest, mode_selection('walk'), 'walk', G)) is None:
                    print(f'Could not determine travel time between point {center} and the closest parking/rental location. Not possible to determine point isochrones')
                    return None
                
                travel_data = store_parking(MODE, center, nearest, travel_data, travel_time_start, point_isochrones=True)
                
        start = nearest if nearest else center
        mode = {'car_sharing': 'self-drive-car', 'bicycle_rental': 'cycle'}.get(MODE, MODE)
        mode_xml = mode_selection(mode)
        
        for radial_point in points:
            # Not yet handles None cases and RateLimitExceeded from function correctly
            additional_travel_time = travel_time_start
            if rental:
                nearest_end, _, _ = process_location_request(radial_point, radius, restriction_type, poi_filter, polygon, idx, MODE, G, travel_data, num_results=1, rental=rental, include_pt_modes=False, public_transport_modes=public_transport_modes)
                if not nearest_end:
                    print(f'No valid rental found near endpoint {radial_point}. Skipping point. ')
                    continue
                nearest_end=nearest_end[0]
                if (travel_time_end := process_and_get_travel_time(radial_point, nearest_end, mode_selection('walk'), 'walk', G)) is None:
                    print(f'Could not determine travel time between endpoint {radial_point} and the closest rental location. Skipping point')
                    continue
                additional_travel_time+=travel_time_end
                radial_point = nearest_end
                
            if (travel_time_mode := process_and_get_travel_time(start, radial_point, mode_xml, mode, G)) is None:
                print(f'Could not determine the final travel time using {MODE}. Skipping point. ')
                continue
            
            travel_time = additional_travel_time + travel_time_mode
            print(f'Successfully determined a travel time of {travel_time} from {start} to {radial_point} using mode: {MODE}')
            travel_times.append(travel_time)
            valid_points.append(radial_point)
        
    except RateLimitExceededError as e:
        print(f'Rate limit exceeded! Point isochrones for point {center} may appear incomplete.')
        
    travel_data = store_point_travel_time(MODE, center, valid_points, travel_times, travel_data)
    return travel_data