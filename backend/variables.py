from datetime import datetime, timezone
import xml.etree.ElementTree as ET

KEY = '57c5dbbbf1fe4d000100001842c323fa9ff44fbba0b9b925f0c052d1'
#KEY = 'eyJvcmciOiI2NDA2NTFhNTIyZmEwNTAwMDEyOWJiZTEiLCJpZCI6IjdiNjAwODM5ZGExZDRhYTM5ODlhNjEwNTc5Mjg0ZjAwIiwiaCI6Im11cm11cjEyOCJ9'
ARR = datetime(2025, 3, 23, 14, 30, 0).isoformat()
TIMESTAMP = datetime.now(timezone.utc).isoformat()
ENDPOINT = "https://api.opentransportdata.swiss/ojp2020"
POI_TEMPLATE = 'templates/poi_filter.xml'
MODE_TEMPLATE = 'templates/mode_specification.xml'
MONO_MODE = True
WALKING_NETWORK = True # Set to False to use OJP to calculate all walking travel times
NETWORK_AREA = "Zurich, Zurich, Switzerland"
SEED = 82
WALKING_SPEED = 4.0*1000/(60*60) # 4km/h -> m/s
NETWORK_ISOCHRONES = False # Set to True to calculate isochrones for the entire network
USE_MODE_WEIGHTING = True # Set to True if the nearest station and the acceptable walking distance should consider station importance -> weighted by number of modes at each station
BASE_GRID_SIZE = 500  # Meters (adjustable for different resolutions) -> used to sample points (1 point per grid, additional points depending on number of intersections per grid)
EXTRA_POINTS = 100  # Increase density in high-importance areas by adding this any additional points to the grid. The total number of points depends on the chosen BASE_GRID_SIZE
# If EXTRA_POINTS set to 0, no intersections will be calculated. Note that intersection calculation is computationaly expensive for larger areas with a smaller BASE_GRID_SIZE
IMPROVE_ISOCHRONES = True # Set to True if resulting isochrones should be checked for larger areas of the same travel time, and areas without travel times, and sample additional points in these areas to improve the isochrones

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

DATASETS_STATIC = {
    "zurich-bicycles-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_zweiradparkierung",
        "json_file": "data/zurich_bicycles_parking.json",
    },
    "zurich-street-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_strassenparkplaetze_ogd",
        "json_file": "data/zurich_street_parking.json",
    },
    "zurich-public-parking-garages": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_parkhaeuser",
        "json_file": "data/zurich_car_park.json",
    }
}

DATA_PATH = 'data/travel_times.pkl'
DENSITY_DATA_PATH = 'data/intersection_density.pkl'

TIMESTAMP_FILE = "data/data_timestamps.txt"

MODE='self-drive-car' # Possible: walk, cycle, self-drive-car, bicycle_rental, escooter_rental, car_sharing