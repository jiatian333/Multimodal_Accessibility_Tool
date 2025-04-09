from datetime import datetime, timezone
from pathlib import Path

# Quick adjustments
KEY = '57c5dbbbf1fe4d000100001842c323fa9ff44fbba0b9b925f0c052d1' # Publically accessible kex
#KEY = 'eyJvcmciOiI2NDA2NTFhNTIyZmEwNTAwMDEyOWJiZTEiLCJpZCI6IjdiNjAwODM5ZGExZDRhYTM5ODlhNjEwNTc5Mjg0ZjAwIiwiaCI6Im11cm11cjEyOCJ9'
MODE='bicycle_rental' # Possible: walk, cycle, self-drive-car, bicycle_rental, escooter_rental, car_sharing
NETWORK_ISOCHRONES = True # Set to True to calculate isochrones for the entire network
INPUT_STATION = 'Zürich, Haldenegg' #'Zürich, Haldenegg' 'Zürich, Zoo' 'Zürich, Bahnhofquai/HB'

ARR = datetime(2025, 4, 13, 14, 30, 0).isoformat() # Arrival time -> set outside rush hour to prevent bias
TIMESTAMP = datetime.now(timezone.utc).isoformat() # Current timestamp
ENDPOINT = "https://api.opentransportdata.swiss/ojp2020" # API endpoint of OJP 1.0

WALKING_NETWORK = True # Set to False to use OJP to calculate all walking travel times
NETWORK_AREA = "Zürich (Canton), Switzerland" # Can load a bit a larger area so that it still considers rental stations, public transport stations and parking outside the core area -> Warning: loading this walking network takes ~8min
CITY_AREA = "Zurich, Zurich, Switzerland" # Focus area for point selection
SEED = 82 # Set for reproducible results
WALKING_SPEED = 4.0*1000/(60*60) # 4km/h -> m/s same standard as in OJP, used if WALKING_NETWORK=True

USE_RTREE_SEARCH = True # If first attempt r-tree search to determine nearest public transport stations and rental stations. Will still default to OJP if the search fails.
USE_MODE_WEIGHTING = True # Set to True if the nearest station and the acceptable walking distance should consider station importance -> weighted by number of modes at each station
BASE_GRID_SIZE = 500  # Meters (adjustable for different resolutions) -> used to sample points (1 point per grid, additional points depending on number of intersections per grid)
EXTRA_POINTS = 250  # Increase density in high-importance areas by adding additional points to the grid. The total number of points depends on the chosen BASE_GRID_SIZE
# If EXTRA_POINTS set to 0, no intersections will be calculated. Note that intersection calculation is computationaly expensive for larger areas with a smaller BASE_GRID_SIZE
IMPROVE_ISOCHRONES = True # Set to True if resulting isochrones should be checked for larger areas of the same travel time, and areas without travel times, and sample additional points in these areas to improve the isochrones

# Most important paths to the folders
TEMPLATES_PATH = 'templates/' # Path to templates folder
DATA_PATH = 'data/' # Path to the main data
LOGIN_PATH = DATA_PATH+"login/" # Path to json file containing the login information
PARKING_PATH = DATA_PATH+'parking/'
SHARED_PATH = DATA_PATH+'shared_mobility/'
INTERSECTIONS_PATH = DATA_PATH+'intersections/'
MAIN_DATABASE_PATH = DATA_PATH+'database/'
PUBLIC_TRANSIT_PATH = DATA_PATH+'public_transit/'

# Make sure the directories exist:
for path in [DATA_PATH, TEMPLATES_PATH, SHARED_PATH, PARKING_PATH, LOGIN_PATH, INTERSECTIONS_PATH, MAIN_DATABASE_PATH, PUBLIC_TRANSIT_PATH]:
    Path(path).mkdir(parents=True, exist_ok=True)

# Further files used for calculations (located under the major folders)
LOGIN = LOGIN_PATH+"dblogin_nick.json"
POI_TEMPLATE = TEMPLATES_PATH+'poi_filter.xml'
MODE_TEMPLATE = TEMPLATES_PATH+'mode_specification.xml'
STORED_POINTS = MAIN_DATABASE_PATH+'stored_data.pkl'
DENSITY = INTERSECTIONS_PATH+'intersection_density.pkl'
TIMESTAMP_FILE = PARKING_PATH+"data_timestamps.txt"
TRANSPORT_STATIONS = PUBLIC_TRANSIT_PATH+"service_points.csv" # Downloaded from: https://data.opentransportdata.swiss/en/dataset/service-points-full
RENTAL_PROVIDERS = DATA_PATH+"rental_providers.json" # Downloaded from: https://sharedmobility.ch/providers.json 
RENTAL_STATIONS = DATA_PATH+"rental_station_information.json" # Downloaded from https://sharedmobility.ch/station_information.json 

# Note do not change the keys of these dictionarys as they are called accordingly in the main.py file
# Additionally, the DATASETS_STATIC only contain parking facilities in Zurich (keep in mind if NETWORK_AREA is changed) -> might require some further adjustments when filter_and_combine_json_files is called in main.py
DATASETS = {
    "parking-facilities": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities/permalink",
        "json_file": PARKING_PATH+"parking-facilities.json",
    },
    "bike-parking": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking/permalink",
        "json_file": PARKING_PATH+"bike_parking.json",
    }
}

DATASETS_STATIC = {
    "zurich-bicycles-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_zweiradparkierung",
        "json_file": PARKING_PATH+"zurich_bicycles_parking.json",
    },
    "zurich-street-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_strassenparkplaetze_ogd",
        "json_file": PARKING_PATH+"zurich_street_parking.json",
    },
    "zurich-public-parking-garages": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_parkhaeuser",
        "json_file": PARKING_PATH+"zurich_car_park.json",
    }
}

COMBINED_DATASETS = {
    "json_file_bike_parking": PARKING_PATH+"total_bike_parking.json",
    "json_file_car_parking": PARKING_PATH+"total_car_parking.json"
}

# Shared mobility information

SHARED_TIMESTAMP_FILE = SHARED_PATH+'data_timestamps.txt'

SHARED_MOBILITY_FEEDS = {
    "providers": {
        "url": "https://sharedmobility.ch/providers.json",
        "json_file": SHARED_PATH + "providers.json",
    },
    "station_information": {
        "url": "https://sharedmobility.ch/station_information.json",
        "json_file": SHARED_PATH + "station_information.json",
    },
    "free_bike_status": {
        "url": "https://sharedmobility.ch/free_bike_status.json",
        "json_file": SHARED_PATH + "free_bike_status.json",
    },
    "station_status": {
        "url": "https://sharedmobility.ch/station_status.json",
        "json_file": SHARED_PATH + "station_status.json",
    }
}

COMBINED_SHARED_MOBILITY = {
    "json_file_modes": SHARED_PATH + "mode_locations.json"
}

GBFS_MASTER_URL = "https://sharedmobility.ch/gbfs.json"