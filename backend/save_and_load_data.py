from variables import *
import pickle
import os
import osmnx as ox
import json

def save_data(travel_data):
    """ Saves travel time data to disk. """
    with open(DATA_PATH, "wb") as f:
        pickle.dump(travel_data, f)
    print(f"✅ Data saved to {DATA_PATH}")

def load_data():
    """ Loads travel time data from disk if available. """
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "rb") as f:
            travel_data = pickle.load(f)
        print("✅ Precomputed travel time data loaded!")
    else:
        print("⚠️ No precomputed data found!!")
        travel_data = initialize_travel_data()
    return travel_data

def initialize_travel_data():
    modes = ['walk', 'cycle', 'self-drive-car', 'bicycle_rental', 'escooter_rental', 'car_sharing']
    travel_data = {mode: {"isochrones": {}, "point_isochrones": {}} for mode in modes}

    for mode in ['bicycle_rental', 'escooter_rental', 'car_sharing']:
        travel_data[mode]['rental'] = {}
    
    travel_data['bike-parking'] = {}
    travel_data['car-parking'] = {}
    
    travel_data['point_isochrones'] = {'bike-parking': {}, 'car-parking': {}}
    
    return travel_data

def store_travel_time(mode, origin, destination, travel_time, travel_data):
    """ Stores travel time information in a nested dictionary. """
    travel_data[mode]['isochrones'][origin] = {
        "destination": destination,
        "travel_time": travel_time
    }
    return travel_data

def store_point_travel_time(mode, center, points, travel_times, travel_data):
    travel_data[mode]["point_isochrones"][center] = {
        "points": points,
        "travel_times": travel_times
    }
    return travel_data

def get_stored_parking_info(travel_data, point, mode, point_isochrones=False):
    parking_type = {
        'cycle': 'bike-parking', 'bicycle_rental': 'bike-parking', 'escooter_rental': 'bike-parking',
        'self-drive-car': 'car-parking', 'car_sharing': 'car-parking'
    }.get(mode)
    
    if point in travel_data[parking_type]:
        print('Retrieving stored parking information.')
        return travel_data[parking_type][point]['parking'], travel_data[parking_type][point]['travel_time']
    
    if point_isochrones and point in travel_data['point_isochrones'].get(parking_type, {}):
        print('Retrieving stored parking information from point isochrones.')
        return travel_data['point_isochrones'][parking_type][point]['parking'], travel_data['point_isochrones'][parking_type][point]['travel_time']
    
    return None, None

def store_parking(mode, station, parking, travel_data, walking_time, point_isochrones=False):
    parking_type = {
        'cycle': 'bike-parking', 'bicycle_rental': 'bike-parking', 'escooter_rental': 'bike-parking',
        'self-drive-car': 'car-parking', 'car_sharing': 'car-parking'
    }.get(mode)
    
    target = travel_data['point_isochrones'] if point_isochrones else travel_data
    
    target[parking_type][station] = {'parking': parking, 'travel_time': walking_time}
    return travel_data

def store_rental_station_info(rental_station, nearest_station, riding_time, mode, travel_data):
    travel_data[mode]['rental'][rental_station] = {
        "nearest_station": nearest_station,
        "travel_time": riding_time
    }
    return travel_data

def save_gdf_as_geojson(gdf, file_path, mode=MODE, center=None):
    """
    Saves a GeoDataFrame as a GeoJSON file with additional metadata.

    Parameters:
    - gdf (geopandas.GeoDataFrame): The GeoDataFrame to save.
    - file_path (str): The path where the GeoJSON file will be saved.
    - metadata (dict, optional): A dictionary of metadata to include in the GeoJSON file.
    
    Returns:
    - None
    """
    # Convert GeoDataFrame to GeoJSON format
    geojson = gdf.to_crs("EPSG:4326").to_json()
    
    type = 'network' if NETWORK_ISOCHRONES else 'point'
    
    metadata = {
    "type": type,
    "mode": mode,
    "center": center
    }

    # If metadata is provided, add it to the file
    # Parse the GeoJSON string into a dictionary
    geojson_dict = json.loads(geojson)
    
    # Add metadata to the properties of the GeoJSON
    geojson_dict['metadata'] = metadata
    
    # Convert back to GeoJSON string
    geojson = json.dumps(geojson_dict, indent=4)

    # Write to a file
    with open(file_path, 'w') as f:
        f.write(geojson)

    print(f"GeoJSON file saved to {file_path}")