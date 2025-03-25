from variables import *
import os
import sys
import time
import osmnx as ox
from rtree import index
from shapely.geometry import Point
os.environ['GDAL_DATA'] = os.path.join(f'{os.sep}'.join(sys.executable.split(os.sep)[:-1]), 'Library', 'share', 'gdal')
from travel_times import network_travel_times, point_travel_times
from update_data import check_for_updates, filter_and_combine_json_files
from build_r_tree import build_rtree
from parameter_selection import get_max_radius
from random_point_selection import generate_adaptive_sample_points, sample_additional_points, generate_radial_grid
from save_and_load_data import save_data, load_data, save_gdf_as_geojson
from isochrones import generate_isochrones
    
def main():
    start_time = time.time()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    #check_for_updates()
    filter_and_combine_json_files(
        dataset_keys=["bike-parking", "zurich-bicycles-parking"],
        output_file="data/total_bike_parking.json",
        exclude_name="Motorrad"
    )

    filter_and_combine_json_files(
        dataset_keys=["parking-facilities", "zurich-street-parking", "zurich-public-parking-garages"],
        output_file="data/total_car_parking.json",
        include_art=["Blaue Zone", "Weiss markiert"]
    )
    
    travel_data = load_data()
    
    idx = index.Index()
    idx = build_rtree(idx)
    
    G = ox.graph_from_place(NETWORK_AREA, network_type="walk")
    city_poly = ox.geocode_to_gdf(NETWORK_AREA)
    water_gdf = ox.features_from_place(NETWORK_AREA, tags={"natural": "water"}).union_all()
    river_gdf = ox.features_from_place(NETWORK_AREA, tags={"waterway": True}).union_all()
    water_combined = water_gdf.union(river_gdf)
    
    if NETWORK_ISOCHRONES:
        random_points = generate_adaptive_sample_points(city_poly, mode=MODE)
        city_poly = city_poly.geometry.union_all()
        travel_data = network_travel_times(travel_data, random_points, G, city_poly, idx)
        save_data(travel_data)
        isochrones, center = generate_isochrones(travel_data, MODE, water_combined, city_poly)
        
        if IMPROVE_ISOCHRONES:
            print('Searching for additional points to improve the isochrones')
            new_points = sample_additional_points(isochrones, city_poly, n_unsampled=100, n_large_isochrones=50)
            travel_data = network_travel_times(travel_data, new_points, G, city_poly, idx)
            save_data(travel_data)
            isochrones, center = generate_isochrones(travel_data, MODE, water_combined, city_poly)
    else:
        input_coordinates = (47.3769, 8.5417)
        max_radius = get_max_radius(MODE)
        
        center = Point(input_coordinates[::-1])
        points = generate_radial_grid(center, city_poly, max_radius, num_rings=4, base_points=6, offset_range=50)
        city_poly = city_poly.geometry.union_all()
        
        # Currently only for walk -> adjust
        if (travel_data := point_travel_times(travel_data, center, points, idx, G, mode=MODE)) is None:
            raise ValueError(f'No isochrones computed for point {center} due to an error')
        save_data(travel_data)
        isochrones, center = generate_isochrones(travel_data, MODE, water_combined, city_poly)
    
    # Adjust to save to dababase instaec of a local file
    save_gdf_as_geojson(isochrones, 'isochrones.geojson', MODE, center)
    end_time = time.time()

    # Calculate elapsed time
    elapsed_time = end_time - start_time
    print(f"Execution Time: {elapsed_time} seconds")
    
          
if __name__=='__main__':
    main()