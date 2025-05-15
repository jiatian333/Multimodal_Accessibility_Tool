"""
Project Configuration and Constants

This module centralizes configuration settings, paths, and constants
used across the isochrone generation project.

Contents:
---------
- API and endpoint settings (e.g., OJP API key, prefixes)
- Feature flags for algorithm behavior and performance tuning
- Geographic definitions and coordinate reference systems (CRS)
- Directory and file path structure for data access and storage
- External dataset URLs and mappings for parking and shared mobility
- Shared mobility feed URLs for real-time data
- Supported transport mode definitions for multimodal analysis

Key Concepts:
-------------
- Feature Flags: Toggle algorithm behavior like mode weighting or graph-based walking.
- Dataset Dictionaries: Control which JSON files to load for parking/shared mobility.
- Paths: Dynamically resolved based on root, ensuring portable file structure.

Usage:
------
Import any constant from this module for use in the application:

    from app.core.config import API_PREFIX, CITY_AREA, DATASETS

Environment Variables:
----------------------
- `.env` file used for loading API keys and database credentials.
- OSMnx caching is enabled by default to reduce network usage.

Notes:
------
- Constants use `Final` from `typing` to indicate immutability.
- Directory creation ensures all required data paths exist on startup.
"""

from dotenv import load_dotenv
import os
import osmnx as ox
ox.settings.use_cache = True

import asyncio
from pathlib import Path
from typing import Dict, Final, Literal, Set

# === General API Settings ===

load_dotenv()
KEY: Final[str] = os.getenv("API_KEY", "") # API key
DB_CREDENTIALS: Final[Dict[str, str]] = {
    "user": os.getenv("DB_USER", ""),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", ""),
    "port": os.getenv("DB_PORT", ""),
    "dbname": os.getenv("DB_NAME", "")
}

ENDPOINT: Final[str] = "https://api.opentransportdata.swiss/ojp2020" # OJP API endpoint
API_PREFIX: Final[str] = "/api/compute"
FRONTEND: Final[str] = "http://127.0.0.1:5500" # Location of the frontend

# === Algorithm Behavior Flags ===

IMPROVE_ISOCHRONES: Final[bool] = True  # Resample in problematic or large uniform regions
USE_MODE_WEIGHTING: Final[bool] = True  # Weight stations by number of modes (account for station importance)
USE_RTREE_SEARCH: Final[bool] = True # Use R-tree index before falling back to API
ONLY_OJP: Final[bool] = True # Whether to only rely on OJP for point isochrones if performance mode is activated (significant speed increase)
WALKING_NETWORK: Final[bool] = True     # Use local walking network instead of API

# Maximum number of destination candidates evaluated per origin point, restricted by `MAX_DESTINATIONS` if walking requirements fulfilled. 
NUM_RESULTS_DESTINATIONS: Final[int] = 30 # Increase if often no valid station found for network isochrones.

# Number of top-ranked destinations per origin used in final evaluation
MAX_DESTINATIONS: Final[int] = 3 # Higher = better accuracy, but significantly slower (evaluates more candidate pairs)

# === OJP Restrictions ===
OJP_SEMAPHORE: Final[asyncio.Semaphore] = asyncio.Semaphore(100)  # allow up to 100 concurrent OJP requests
RATE_LIMIT: Final[int] = 100 # Max 100 calls per minute quota
RATE_PERIOD: Final[int] = 60

# === Geographic and Sampling Settings ===

NETWORK_AREA: Final[str] = "Zürich (Canton), Switzerland"  # Network load extent, larger areas lead to significant performance loss
CITY_AREA: Final[str] = "Zurich, Zurich, Switzerland"  # Focus area for isochrones
WATER_AREA: Final[str] = "Switzerland" # Exclude water areas for the entirety of Switzerland

SOURCE_CRS: Final[int] = 4326 # WGS84
TARGET_CRS: Final[int] = 2056 # Swiss LV95

SEED: Final[int] = 82  # Random seed for reproducibility
WALKING_SPEED: Final[float] = 4.0 * 1000 / 3600  # Walking speed in m/s
WATER_DIFF_TIMEOUT: Final[float] = 5.0 # For performance mode, max time available for water differencing before fallback

BASE_GRID_SIZE: Final[int] = 500  # Meters between sampled grid centers

# Add points in dense/intersection-heavy areas
EXTRA_POINTS: Final[int] = 100 # setting to 0 can prevent performance loss from intersection calculation (especially for small BASE_GRID_SIZE)

# === Locks to prevent overwriting data ===
TravelDataLock: Final[asyncio.Lock] = asyncio.Lock()
DistanceCacheLock: Final[asyncio.Lock] = asyncio.Lock()
RateLock: Final[asyncio.Lock] = asyncio.Lock()

# === Directories ===

ROOT_DIR: Final[Path] = Path(__file__).resolve().parents[2]
CACHE_DIR: Final[Path] = ROOT_DIR / "cache"
GRAPH_DIR: Final[Path] = CACHE_DIR / "graphs"
ox.settings.cache_folder = str(CACHE_DIR)
TEMPLATES_PATH: Final[Path] = ROOT_DIR / "templates"
DATA_PATH: Final[Path] = ROOT_DIR / "data"
PARKING_PATH: Final[Path] = DATA_PATH / "parking"
SHARED_PATH: Final[Path] = DATA_PATH / "shared_mobility"
INTERSECTIONS_PATH: Final[Path] = DATA_PATH / "intersections"
MAIN_DATABASE_PATH: Final[Path] = DATA_PATH / "database"
PUBLIC_TRANSIT_PATH: Final[Path] = DATA_PATH / "public_transit"
LOG_PATH: Final[Path] = DATA_PATH / "logs"

# Ensure required directories exist
for path in [
    TEMPLATES_PATH, DATA_PATH, PARKING_PATH, SHARED_PATH, CACHE_DIR, GRAPH_DIR,
    INTERSECTIONS_PATH, MAIN_DATABASE_PATH, PUBLIC_TRANSIT_PATH, LOG_PATH
]:
    path.mkdir(parents=True, exist_ok=True)

# === Template & Static Files ===

POI_TEMPLATE: Final[Path] = TEMPLATES_PATH / "poi_filter.xml"
MODE_TEMPLATE: Final[Path] = TEMPLATES_PATH / "mode.xml"
STORED_POINTS: Final[Path] = MAIN_DATABASE_PATH / "stored_data.pkl"
DISTANCE_FILE: Final[Path] = MAIN_DATABASE_PATH / "distances.pkl"
DENSITY: Final[Path] = INTERSECTIONS_PATH / "intersection_density.pkl"
TIMESTAMP_FILE: Final[Path] = PARKING_PATH / "data_timestamps.txt"
TRANSPORT_STATIONS: Final[Path] = PUBLIC_TRANSIT_PATH / "service_points.csv" # https://data.opentransportdata.swiss/en/dataset/service-points-full
RENTAL_PROVIDERS: Final[Path] = DATA_PATH / "rental_providers.json" # https://sharedmobility.ch/providers.json 
RENTAL_STATIONS: Final[Path] = DATA_PATH / "rental_station_information.json" # https://sharedmobility.ch/station_information.json 
LOG_FILE: Final[Path] = LOG_PATH / "debug.log"

# === Dataset URLs and File Mappings ===

# Changes to these dictionaries need to be accounted for in main.py as well. 
# Datasets currently only contain additional parking spots in Zurich, might benefit from expansion if geographic settings are changed
DATASETS: Final[Dict[str, Dict[str, str]]]  = {
    "parking-facilities": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/parking-facilities/permalink",
        "json_file": str(PARKING_PATH / "parking-facilities.json"),
    },
    "bike-parking": {
        "webpage_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking",
        "permalink_url": "https://data.opentransportdata.swiss/en/dataset/bike-parking/permalink",
        "json_file": str(PARKING_PATH / "bike_parking.json"),
    }
}

DATASETS_STATIC: Final[Dict[str, Dict[str, str]]] = {
    "zurich-bicycles-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_zweiradparkierung",
        "json_file": str(PARKING_PATH / "zurich_bicycles_parking.json"),
    },
    "zurich-street-parking": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_strassenparkplaetze_ogd",
        "json_file": str(PARKING_PATH / "zurich_street_parking.json"),
    },
    "zurich-public-parking-garages": {
        "webpage_url": "https://data.stadt-zuerich.ch/dataset/geo_oeffentlich_zugaengliche_parkhaeuser",
        "json_file": str(PARKING_PATH / "zurich_car_park.json"),
    }
}

COMBINED_DATASETS: Final[Dict[str, str]] = {
    "json_file_bike_parking": str(PARKING_PATH / "total_bike_parking.json"),
    "json_file_car_parking": str(PARKING_PATH / "total_car_parking.json")
}

# === Shared Mobility Feeds ===

SHARED_TIMESTAMP_FILE: Final[Path] = SHARED_PATH / "data_timestamps.txt"

SHARED_MOBILITY_FEEDS: Final[Dict[str, Dict[str, str]]] = {
    "providers": {
        "url": "https://sharedmobility.ch/providers.json",
        "json_file": str(SHARED_PATH / "providers.json"),
    },
    "station_information": {
        "url": "https://sharedmobility.ch/station_information.json",
        "json_file": str(SHARED_PATH / "station_information.json"),
    },
    "free_bike_status": {
        "url": "https://sharedmobility.ch/free_bike_status.json",
        "json_file": str(SHARED_PATH / "free_bike_status.json"),
    },
    "station_status": {
        "url": "https://sharedmobility.ch/station_status.json",
        "json_file": str(SHARED_PATH / "station_status.json"),
    }
}

COMBINED_SHARED_MOBILITY: Final[Dict[str, str]] = {
    "json_file_modes": str(SHARED_PATH / "mode_locations.json")
}

GBFS_MASTER_URL: Final[str] = "https://sharedmobility.ch/gbfs.json"

# === Supported Modes ===

RENTAL_MODES: Final[Set[str]] = {
    "escooter_rental",
    "bicycle_rental",
    "car_sharing"
}

TransportModes = Literal[
    "walk",
    "cycle",
    "escooter_rental",
    "bicycle_rental",
    "self-drive-car",
    "car_sharing"
]

# --- R-Tree Search Constants ---

LOOKUP = Literal[
    "cycle",
    "escooter_rental",
    "bicycle_rental",
    "self-drive-car",
    "car_sharing",
    "public-transport"
]

MODE_MAP: Final[Dict[LOOKUP, str]] = {
    "cycle": "bike-parking",
    "escooter_rental": "escooter-rental",
    "bicycle_rental": "bike-rental",
    "self-drive-car": "parking-facilities",
    "car_sharing": "car-rental",
    "public-transport": "public-transport"
}