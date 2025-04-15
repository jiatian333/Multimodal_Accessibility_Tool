#!/usr/bin/env python
# coding: utf-8

from variables import COMBINED_DATASETS, NETWORK_AREA, CITY_AREA, IMPROVE_ISOCHRONES
import os
import sys
import pyproj
import osmnx as ox
from shapely.geometry import Point

# Set GDAL environment variable
os.environ['GDAL_DATA'] = os.path.join(f'{os.sep}'.join(sys.executable.split(os.sep)[:-1]), 'Library', 'share', 'gdal')
os.environ['OMP_NUM_THREADS'] = '1'  # Limit threads to 1

from travel_times import network_travel_times, point_travel_times
from update_data import check_for_updates, filter_and_combine_json_files, process_shared_mobility_data
from build_r_tree import build_rtree
from parameter_selection import get_max_radius
from random_point_selection import generate_adaptive_sample_points, sample_additional_points, generate_radial_grid
from save_and_load_data import save_data, load_data, save_to_database, load_public_transport_stations, check_entry_exists, check_travel_data_integrity
from isochrones import generate_isochrones

# Variables received from input
MODE='cycle' # Possible: walk, cycle, self-drive-car, bicycle_rental, escooter_rental, car_sharing
NETWORK_ISOCHRONES = True # Set to True to calculate isochrones for the entire network
INPUT_STATION = 'Zürich, Haldenegg' #'Zürich, Haldenegg' 'Zürich, Zoo' 'Zürich, Bahnhofquai/HB'
PERFORMANCE = False # Set to True if point isochrones should be computed as efficiently as possible. This lowers the max number of points and max radius significantly. It also only make use of the walking network of the city area due to much faster computations, but isochrones will be constrained to the city boundaries as a result

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    '''if check_entry_exists('network' if NETWORK_ISOCHRONES else 'point', MODE, INPUT_STATION):
        return'''
    
    #check_for_updates()
    #process_shared_mobility_data()
    filter_and_combine_json_files(["bike-parking", "zurich-bicycles-parking"], COMBINED_DATASETS['json_file_bike_parking'], exclude_name="Motorrad")
    filter_and_combine_json_files(["parking-facilities", "zurich-street-parking", "zurich-public-parking-garages"], COMBINED_DATASETS['json_file_car_parking'], include_art=["Blaue Zone", "Weiss markiert"])
    
    travel_data = load_data()
    if not check_travel_data_integrity(travel_data):
        print('Travel data corrupted. Please validate accuracy before continuing')
        return
    public_transport_stations = load_public_transport_stations()
    idx = build_rtree(public_transport_stations)
    
    G_canton = ox.graph_from_place(NETWORK_AREA, network_type="walk")
    G_city = ox.graph_from_place(CITY_AREA, network_type="walk")
    city_poly = ox.geocode_to_gdf(CITY_AREA).geometry.union_all()
    canton_poly = ox.geocode_to_gdf(NETWORK_AREA).geometry.union_all()
    water_gdf = ox.features_from_place(NETWORK_AREA, tags={"natural": "water"}).geometry.union_all()
    river_gdf = ox.features_from_place(NETWORK_AREA, tags={"waterway": True}).geometry.union_all()
    water_combined = water_gdf.union(river_gdf)
    target_crs = pyproj.CRS.from_epsg(2056)
    
    if NETWORK_ISOCHRONES:
        random_points = generate_adaptive_sample_points(city_poly, water_combined, target_crs, mode=MODE)
        travel_data = network_travel_times(travel_data, random_points, G_canton, canton_poly, idx, public_transport_stations, MODE)
        save_data(travel_data)
        isochrones, center = generate_isochrones(travel_data, MODE, water_combined, city_poly, network_isochrones=NETWORK_ISOCHRONES)
        
        if IMPROVE_ISOCHRONES:
            print('Searching for additional points to improve the isochrones')
            new_points = sample_additional_points(isochrones, city_poly, water_combined, n_unsampled=100, n_large_isochrones=150)
            travel_data = network_travel_times(travel_data, new_points, G_canton, canton_poly, idx, public_transport_stations, MODE)
            save_data(travel_data)
            isochrones, center = generate_isochrones(travel_data, MODE, water_combined, city_poly, network_isochrones=NETWORK_ISOCHRONES)
    else:
        train_stations = load_public_transport_stations(city_poly=city_poly, trains=True)
        lookup = public_transport_stations.set_index("name")[["longitude", "latitude"]].to_dict("index")
        coords = lookup.get(INPUT_STATION)
        center = Point((coords['longitude'], coords['latitude']))
        max_radius=get_max_radius(MODE, PERFORMANCE)
        polygon = city_poly if PERFORMANCE else canton_poly
        graph = G_city if PERFORMANCE else G_canton
        
        points = generate_radial_grid(center, polygon, water_combined, max_radius, target_crs, MODE, PERFORMANCE)
        
        if (travel_data := point_travel_times(travel_data, center, points, idx, graph, polygon, public_transport_stations, mode=MODE)) is None:
                return
            
        save_data(travel_data)
        isochrones, center = generate_isochrones(travel_data, MODE, water_combined, polygon, center=center, performance=PERFORMANCE, network_isochrones=NETWORK_ISOCHRONES, input_station=INPUT_STATION)
    
    #save_to_database(isochrones)
    
          
if __name__=='__main__':
    main()