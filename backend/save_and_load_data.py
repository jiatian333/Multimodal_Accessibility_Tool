from variables import *
import pickle
import pandas as pd
import os
import json
import psycopg2
from psycopg2.extras import execute_values
from shapely.geometry import mapping

def save_data(travel_data):
    """ Saves travel time data to disk. """
    with open(STORED_POINTS, "wb") as f:
        pickle.dump(travel_data, f)
    print(f"✅ Data saved to {STORED_POINTS}")

def load_data():
    """ Loads travel time data from disk if available. """
    if os.path.exists(STORED_POINTS):
        with open(STORED_POINTS, "rb") as f:
            travel_data = pickle.load(f)
        print("✅ Precomputed travel time data loaded!")
        return travel_data
    
    print("⚠️ No precomputed data found!!")
    return initialize_travel_data()

def initialize_travel_data():
    """ Initializes the travel data structure. """
    modes = ['walk', 'cycle', 'self-drive-car', 'bicycle_rental', 'escooter_rental', 'car_sharing']
    travel_data = {mode: {"isochrones": {}, "point_isochrones": {}} for mode in modes}

    for mode in ['bicycle_rental', 'escooter_rental', 'car_sharing']:
        travel_data[mode]['rental'] = {}
        travel_data[mode]['station_rental'] = {}
        travel_data[mode]['station_rental']['point_isochrones'] = {}
    
    travel_data.update({
        'bike-parking': {},
        'car-parking': {},
        'point_isochrones': {'bike-parking': {}, 'car-parking': {}}
    })
    
    return travel_data

def store_travel_time(mode, origin, destination, travel_time, travel_data):
    """ Stores travel time information in a nested dictionary. """
    travel_data[mode]['isochrones'][origin] = {
        "destination": destination,
        "travel_time": travel_time
    }
    return travel_data

def store_point_travel_time(mode, center, points, travel_times, travel_data):
    """ Stores point-based travel time data. """
    travel_data[mode]["point_isochrones"][center] = {
        "points": points,
        "travel_times": travel_times
    }
    return travel_data

def get_parking_type(mode):
    parking_type = parking_type = {
        'cycle': 'bike-parking', 'bicycle_rental': 'bike-parking', 'escooter_rental': 'bike-parking',
        'self-drive-car': 'car-parking', 'car_sharing': 'car-parking'
    }
    return parking_type.get(mode)

def get_stored_parking_info(travel_data, point, mode, point_isochrones=False):
    """ Retrieves stored parking information if available. """
    
    parking_type = get_parking_type(mode)
    
    if point in travel_data[parking_type]:
        print('Retrieving stored parking information.')
        return travel_data[parking_type][point]['parking'], travel_data[parking_type][point]['travel_time']
    
    if point_isochrones and point in travel_data['point_isochrones'][parking_type]:
        print('Retrieving stored parking information.')
        return travel_data['point_isochrones'][parking_type][point]['parking'], travel_data['point_isochrones'][parking_type][point]['travel_time']
    
    return None, None

def store_parking(mode, station, parking, travel_data, walking_time, point_isochrones=False):
    """ Stores parking information. """
    
    parking_type = get_parking_type(mode)
    
    storage = travel_data['point_isochrones'][parking_type] if point_isochrones else travel_data[parking_type]
    storage[station] = {'parking': parking, 'travel_time': walking_time}
    
    return travel_data

def get_stored_closest_rental(travel_data, mode, destination, point_isochrones=False):
    
    if destination in travel_data[mode]['station_rental']:
        print('Retrieving stored rental information.')
        return travel_data[mode]['station_rental'][destination]['nearest_rental'], travel_data[mode]['station_rental'][destination]['travel_time']
    
    if point_isochrones and destination in travel_data[mode]['station_rental']['point_isochrones']:
        print('Retrieving stored rental information.')
        return travel_data[mode]['station_rental']['point_isochrones'][destination]['nearest_rental'], travel_data[mode]['station_rental']['point_isochrones'][destination]['travel_time']
    
    return None, None

def store_closest_rental(travel_data, mode, destination, rental_station, walking_time, point_isochrones=False):
    
    storage = travel_data[mode]['station_rental']['point_isochrones'] if point_isochrones else travel_data[mode]['station_rental']
    
    storage[destination] = {
        'nearest_rental': rental_station,
        'travel_time': walking_time
    }
    return travel_data

def store_rental_station_info(rental_station, nearest_dest, riding_time, mode, travel_data):
    """ Stores rental station information. """
    
    travel_data[mode]['rental'][rental_station] = {
        "nearest": nearest_dest,
        "travel_time": riding_time
    }
    return travel_data

def load_public_transport_stations():
    # Load dataset (modify as needed)
    dtype_dict = {
        "abbreviation": "string",   # Text column
        "districtName": "string",      # Nullable integer
        "operatingPointType": "string",      # Text column
        "categories": "string",            # Text column
        "operatingPointTrafficPointType": "string", 
        "fotComment": "string"# Nullable float
    }

    df = pd.read_csv(TRANSPORT_STATIONS, sep=';', dtype=dtype_dict, header=0, parse_dates=["editionDate", "validFrom"])

    # Filter for Swiss public transport stops
    df = df[(df["isoCountryCode"] == "CH") & (df["stopPoint"] == True)]

    # Sort by editionDate (or validFrom if more suitable)
    df = df.sort_values(by="editionDate", ascending=False)

    # Drop duplicates based on unique stop identifier (e.g., 'numberShort' or 'sloid')
    df = df.drop_duplicates(subset=["numberShort"], keep="first")

    # Select relevant columns
    stops_filtered = df[
        ["designationOfficial", "wgs84East", "wgs84North", "meansOfTransport"]
    ].rename(columns={
        "designationOfficial": "name",
        "wgs84East": "longitude",
        "wgs84North": "latitude",
        "meansOfTransport": "transport_modes"
    })
    
    def resolve_duplicates(group):
        non_unknown = group[group["transport_modes"] != "UNKNOWN"]
        
        if not non_unknown.empty:
            return non_unknown.iloc[0]  # If valid modes exist, keep first one
        return group.iloc[0]

    stops_filtered = stops_filtered.groupby("name", group_keys=False).apply(resolve_duplicates).reset_index(drop=True)
    
    return stops_filtered


def save_to_database(gdf):
    """Saves geodata and metadata (in flat structure) to the database"""

    with open(LOGIN, "r") as infile:
        db_credentials = json.load(infile)

    with psycopg2.connect(**db_credentials) as conn:
        with conn.cursor() as cur:
            try:
                # Create single table with all fields
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS geodata (
                        id SERIAL PRIMARY KEY,
                        level INTEGER,
                        geometry GEOMETRY,
                        type TEXT,
                        mode TEXT,
                        coords_center JSONB,
                        name TEXT
                    );
                """)
                conn.commit()

                # Access global metadata
                meta_dic = gdf.attrs

                # Prepare data for batch insert
                geodata_values = [
                    (
                        int(level),
                        json.dumps(mapping(geometry)),
                        meta_dic.get("type"),
                        meta_dic.get("mode"),
                        json.dumps(meta_dic.get("center")),
                        meta_dic.get("name", None)
                    )
                    for level, geometry in zip(gdf["level"], gdf["geometry"])
                ]

                insert_query = """
                    INSERT INTO geodata (level, geometry, type, mode, coords_center, name)
                    VALUES %s;
                """
                execute_values(cur, insert_query, geodata_values)

                conn.commit()
                print("Successfully saved isochrones to database")

            except Exception as e:
                conn.rollback()
                print("Error while uploading isochrones to database:", e)