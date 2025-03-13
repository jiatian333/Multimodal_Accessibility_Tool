from datetime import datetime, timezone
import xml.etree.ElementTree as ET

KEY = '57c5dbbbf1fe4d000100001842c323fa9ff44fbba0b9b925f0c052d1'
ARR = datetime(2025, 3, 3, 14, 30, 0).isoformat()
TIMESTAMP = datetime.now(timezone.utc).isoformat()
ENDPOINT = "https://api.opentransportdata.swiss/ojp2020"
POI_TEMPLATE = 'templates/poi_filter.xml'
MODE_TEMPLATE = 'templates/mode_specification.xml'
NUM_POINTS=10
MONO_MODE = True
SEED = 61
WALKING_NETWORK = True # Set to False to use OJP to calculate all walking travel times
NETWORK_AREA = "Zurich, Zurich, Switzerland"
WALKING_SPEED = 0.9 #m/s

DATASETS = {
    "parking-facilities": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities/permalink",
        "json_file": "data/parking-facilities.json",
    },
    "bike-parking": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking/permalink",
        "json_file": "data/bike_parking.json",
    }
}
DATA_PATH = 'data/travel_times.pkl'

TIMESTAMP_FILE = "data/data_timestamps.txt"

MODE='escooter_rental' # Possible: walk, cycle, self-drive-car, bicycle_rental, escooter_rental, car_sharing