from variables import *
import pickle
import os
import osmnx as ox

def save_data(travel_data):
    """ Saves travel time data to disk. """
    with open(DATA_PATH, "wb") as f:
        pickle.dump(travel_data, f)
    print(f"✅ Data saved to {DATA_PATH}")
    
def load_walking_network():
    return ox.graph_from_place(NETWORK_AREA, network_type="walk")

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
    travel_data = {mode: {"isochrones": {}} for mode in modes}

    for mode in ['bicycle_rental', 'escooter_rental', 'car_sharing']:
        travel_data[mode]['rental'] = {}
    
    travel_data['bike-parking'] = {}
    travel_data['car-parking'] = {}
    
    return travel_data

def store_travel_time(mode, origin, destination, travel_time, travel_data):
    """ Stores travel time information in a nested dictionary. """
    travel_data[mode]['isochrones'][origin] = {
        "destination": destination,
        "travel_time": travel_time
    }
    return travel_data

def store_parking(mode, station, parking, travel_data, walking_time):
    if mode in ['cycle', 'bicycle_rental', 'escooter_rental']:
        travel_data['bike-parking'][station] = {
            'parking': parking, 
            'travel_time': walking_time
        }
    elif mode in ['self-drive-car', 'car_sharing']:
        travel_data['car-parking'][station] = {
            'parking': parking, 
            'travel_time': walking_time
        }
    return travel_data

def store_rental_station_info(rental_station, nearest_station, riding_time, mode, travel_data):
    travel_data[mode]['rental'][rental_station] = {
        "nearest_station": nearest_station,
        "travel_time": riding_time
    }
    return travel_data