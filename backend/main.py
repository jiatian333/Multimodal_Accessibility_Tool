from variables import *
import os
import sys
os.environ['GDAL_DATA'] = os.path.join(f'{os.sep}'.join(sys.executable.split(os.sep)[:-1]), 'Library', 'share', 'gdal')
import time
from rtree import index
from random_point_selection import extract_polygon_and_generate_points
from helper_functions import process_location_request, process_and_get_travel_time, find_valid_nearest_station
from parameter_selection import select_parameters, mode_selection
from update_data import check_for_updates
from build_r_tree import build_rtree
from save_and_load_data import save_data, load_data, load_walking_network, store_parking, store_rental_station_info, store_travel_time
    
def main():
    start_time = time.time()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    #check_for_updates()
    travel_data = load_data()
    
    idx = index.Index()
    idx = build_rtree(idx)
    
    random_points = extract_polygon_and_generate_points(num_points=NUM_POINTS)
    successful_points = 0
    already_processed_points=0
    
    G = load_walking_network()
    
    for i, random_point in enumerate(random_points):
        if i!=0:
            print('')
            print('----------------------------------------------------------')
            print('')
        if random_point in travel_data[MODE]["isochrones"]:
            print(f"Skipping point: {random_point}, already processed.")
            already_processed_points+=1
            continue
        travel_time = 0
        rental_stored = False
        current_point = random_point
        if MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
            radius, restriction_type, poi_filter = select_parameters(rental=True)
            num_results = 1
            rental_station = process_location_request(random_point, radius, restriction_type, poi_filter, num_results=num_results)[0]
            
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
            destination = process_location_request(current_point, radius, restriction_type, poi_filter, num_results=num_results)
            mode_xml = mode_selection(MODE)
        
        if MODE != 'walk':
            destination, nearest, travel_time_walk = find_valid_nearest_station(idx, destination, MODE, travel_data, G)
            if not nearest:
                continue  # Skip to the next point if no valid station is found
            
            if not rental_stored:
                if not (travel_time_mode := process_and_get_travel_time(current_point, nearest, mode_xml, MODE, G)):
                    continue  # Skip to the next point if trip request failed
                if MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
                    if not (travel_time := process_and_get_travel_time(random_point, rental_station, mode_selection('walk'), 'walk', G)):
                        continue
            
            if travel_time_walk is None:
                if not (travel_time_walk := process_and_get_travel_time(nearest, destination, mode_selection('walk'), 'walk', G)):
                    continue  # Skip to the next point if trip request failed
                store_parking(MODE, destination, nearest, travel_data, travel_time_walk)

            if not rental_stored and MODE in ['escooter_rental', 'bicycle_rental', 'car_sharing']:
                store_rental_station_info(rental_station, destination, travel_time_mode, MODE, travel_data)
            
            travel_time += travel_time_mode + travel_time_walk
        else:
            destination = destination[0]
            if not (travel_time := process_and_get_travel_time(current_point, destination, mode_xml, MODE, G)):
                continue  # Skip to the next point if trip request failed
        
        store_travel_time(MODE, random_point, destination, travel_time, travel_data)
        successful_points+=1
    
    save_data(travel_data)
    print(f"Successfully processed and stored {successful_points} out of {len(random_points)} points.")
    print(f'{already_processed_points} points were already stored in the database.')
    
    end_time = time.time()

    # Calculate elapsed time
    elapsed_time = end_time - start_time
    print(f"Execution Time: {elapsed_time} seconds")
          
if __name__=='__main__':
    main()