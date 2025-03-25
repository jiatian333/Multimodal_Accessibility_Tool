from variables import *
from helper_functions import process_location_request, process_and_get_travel_time, find_valid_nearest_station, find_nearest_using_walking_network, RateLimitExceededError
from parameter_selection import select_parameters, mode_selection
from save_and_load_data import store_parking, get_stored_parking_info, store_travel_time, store_point_travel_time, store_rental_station_info

def network_travel_times(travel_data, random_points, G, polygon, idx):
    successful_points = 0
    already_processed_points=0
    
    for i, random_point in enumerate(random_points):
        if i!=0:
            print('')
            print('----------------------------------------------------------')
            print('')
        if random_point in travel_data[MODE]["isochrones"]:
            print(f"Skipping point: {random_point}, already processed.")
            already_processed_points+=1
            continue
        
        try: 
            travel_time = 0
            rental_stored = False
            current_point = random_point
            if MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
                radius, restriction_type, poi_filter = select_parameters(rental=True)
                num_results = 5
                rental_station, _ = process_location_request(random_point, radius, restriction_type, poi_filter, polygon, num_results=num_results)
                if not rental_station:
                    print('No valid rental station found by OJP. Skipping!')
                    continue
                rental_station = rental_station[0]
                
                if rental_station in travel_data[MODE]['rental']:
                    rental_stored = True
                    rental_info = travel_data[MODE]['rental'][rental_station]
                    
                    if "travel_time" in rental_info and "nearest_station" in rental_info:
                        travel_time_mode = rental_info["travel_time"]
                        destination = [rental_info['nearest_station']]
                        print('Stored Rental Information found and retrieved')
                    else:
                        print('Incomplete rental information. Recomputing!')
                        rental_stored = False  # Recompute if incomplete data exists

                current_point = rental_station
            
            if not rental_stored:
                radius, restriction_type, poi_filter = select_parameters()
                num_results = 10 if MODE != 'walk' else 1
                destination, public_transport_modes = process_location_request(current_point, radius, restriction_type, poi_filter, polygon, num_results=num_results)
                if not destination:
                    print('No valid destination found by OJP. Skipping!')
                    continue
                mode = MODE if MODE not in ['car_sharing', 'bicycle_rental'] else 'self-drive-car' if MODE == 'car_sharing' else 'cycle'
                mode_xml = mode_selection(mode)
            
            if MODE != 'walk':
                destination, nearest, travel_time_walk = find_valid_nearest_station(idx, destination, MODE, travel_data, G, public_transport_modes)
                
                if not nearest:
                    continue  # Skip to the next point if no valid station is found
                
                if not rental_stored:
                    if (travel_time_mode := process_and_get_travel_time(current_point, nearest, mode_xml, mode, G)) is None:
                        continue  # Skip to the next point if trip request failed
                    if MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
                        if (travel_time := process_and_get_travel_time(random_point, rental_station, mode_selection('walk'), 'walk', G)) is None:
                            continue
                
                if travel_time_walk is None:
                    if (travel_time_walk := process_and_get_travel_time(nearest, destination, mode_selection('walk'), 'walk', G)) is None:
                        continue  # Skip to the next point if trip request failed
                    travel_data = store_parking(MODE, destination, nearest, travel_data, travel_time_walk)

                if not rental_stored and MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
                    travel_data = store_rental_station_info(rental_station, destination, travel_time_mode, MODE, travel_data)
                
                travel_time += travel_time_mode + travel_time_walk
            else:
                destination = destination[0]
                if (travel_time := process_and_get_travel_time(current_point, destination, mode_xml, MODE, G)) is None:
                    continue  # Skip to the next point if trip request failed
            
            travel_data = store_travel_time(MODE, random_point, destination, travel_time, travel_data)
            successful_points+=1
            
        except RateLimitExceededError as e:
            print(f"Rate limit exceeded, exiting loop: {e}")
            break  # Exit the loop if rate limit is exceeded
    
    print(f"Successfully processed and stored {successful_points} out of {len(random_points)} points.")
    print(f'{already_processed_points} points were already stored in the database.')
        
    return travel_data
    
    
def point_travel_times(travel_data, center, points, idx, G, mode=MODE):
    travel_times = []
    nearest = None
    
    if mode != 'walk':

        nearest, travel_time_walk = get_stored_parking_info(travel_data, center, mode, point_isochrones=True)
        if not nearest:
            _, nearest = find_nearest_using_walking_network(idx, center.x, center.y, G, mode)
            
            if not nearest:
                print(f'No valid parking found near point {center}')
                return None
            # Determine travel time walk between nearest and center, assume parking is available at end point
            if (travel_time_walk := process_and_get_travel_time(center, nearest, mode_selection('walk'), 'walk', G)) is None:
                print(f'Could not determine travel time between point {center} and the closest parking location')
                return None
            travel_data = store_parking(MODE, center, nearest, travel_data, travel_time_walk, point_isochrones=True)
            
    travel_time_walk = 0 if not nearest else travel_time_walk
    start = nearest if nearest else center
    mode = MODE if MODE not in ['car_sharing', 'bicycle_rental'] else 'self-drive-car' if MODE == 'car_sharing' else 'cycle'
    mode_xml = mode_selection(mode)
    
    for radial_point in points:
        travel_time = travel_time_walk + process_and_get_travel_time(start, radial_point, mode_xml, mode, G)
        travel_times.append(travel_time)
    travel_data = store_point_travel_time(MODE, center, points, travel_times, travel_data)
    return travel_data