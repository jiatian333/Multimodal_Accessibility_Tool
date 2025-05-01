"""
Travel Data Management and Validation

This module manages the lifecycle and integrity of multimodal travel data,
which includes isochrone data, rental station access, and parking information.

Responsibilities:
-----------------
- Initialize the nested `TravelData` structure for various modes.
- Store new isochrone records and point-to-multipoint travel times.
- Validate that existing cached travel data conforms to expected schema.

Functions:
----------
- check_travel_data_integrity(travel_data)
- initialize_travel_data()
- store_travel_time(...)
- store_point_travel_time(...)

Usage:
------
    travel_data = initialize_travel_data()
    store_travel_time("walk", A, B, 4.0, travel_data)
    if not check_travel_data_integrity(travel_data):
        raise ValueError("Corrupted travel structure.")
"""


import logging

from typing import Dict, List
from shapely.geometry import Point

from app.core.config import TravelDataLock, TransportModes
from app.core.data_types import TravelData

logger = logging.getLogger(__name__)

def check_travel_data_integrity(travel_data: TravelData) -> bool:
    """
    Validates internal structure of travel_data object.
    Contains the helper function `validate_entry` to prevent repetitive code. 

    Args:
        travel_data (TravelData): Main multimodal cache.

    Returns:
        bool: True if structure is valid, False otherwise.
    """
    
    def validate_entry(entry: Dict, required_keys: List[str], context: str) -> bool:
        """
        Validates a single dictionary entry for required keys.

        Args:
            entry (Dict): The dictionary to validate (e.g. isochrone, rental, parking).
            required_keys (List[str]): List of keys that must exist in the entry.
            context (str): Description of where the entry came from, for logging.

        Returns:
            bool: True if the entry has all required keys, False otherwise.
        """
        if not isinstance(entry, Dict):
            logger.warning(f"Invalid entry type in {context}: {type(entry)}")
            return False
        for key in required_keys:
            if key not in entry:
                logger.warning(f"Missing key '{key}' in {context}: {entry}")
                return False
        return True

    valid = True

    # --- Network and point isochrones ---
    for mode in ['walk', 'cycle', 'self-drive-car', 'bicycle_rental', 'escooter_rental', 'car_sharing']:
        iso_dict = travel_data.get(mode, {}).get("isochrones", {})
        point_dict = travel_data.get(mode, {}).get("point_isochrones", {})

        for origin, entry in iso_dict.items():
            valid &= validate_entry(entry, ["destination", "travel_time"], f"{mode} isochrone {origin}")
        for center, entry in point_dict.items():
            valid &= validate_entry(entry, ["points", "travel_times"], f"{mode} point_isochrone {center}")

    # --- Rentals ---
    for mode in ['bicycle_rental', 'escooter_rental', 'car_sharing']:
        rental_entries = travel_data.get(mode, {}).get("rental", {})
        station_data = travel_data.get(mode, {}).get("station_rental", {})

        for station, entry in rental_entries.items():
            valid &= validate_entry(entry, ["nearest", "travel_time"], f"{mode} rental ride {station}")
        for group in ["isochrones", "point_isochrones"]:
            for dest, entry in station_data.get(group, {}).items():
                valid &= validate_entry(entry, ["nearest_rental", "travel_time"], f"{mode} rental access {group}:{dest}")

    # --- Parking ---
    for park_type in ["bike-parking", "car-parking"]:
        for station, entry in travel_data.get(park_type, {}).items():
            valid &= validate_entry(entry, ["parking", "travel_time"], f"{park_type} {station}")
        for station, entry in travel_data.get("point_isochrones", {}).get(park_type, {}).items():
            valid &= validate_entry(entry, ["parking", "travel_time"], f"point_{park_type} {station}")

    if valid:
        logger.info("Travel data passed integrity check.")
    else:
        logger.warning("Travel data failed integrity check.")
    return valid


def initialize_travel_data() -> TravelData:
    """
    Initializes an empty TravelData structure for all supported modes.

    Returns:
        TravelData: Nested dictionary with placeholders for each transport mode.
    """
    modes = ['walk', 'cycle', 'self-drive-car', 'bicycle_rental', 'escooter_rental', 'car_sharing']
    travel_data: TravelData = {mode: {"isochrones": {}, "point_isochrones": {}} for mode in modes}

    for mode in ['bicycle_rental', 'escooter_rental', 'car_sharing']:
        travel_data[mode]['rental'] = {}
        travel_data[mode]['station_rental'] = {
            'isochrones': {},
            'point_isochrones': {}
        }

    travel_data.update({
        'bike-parking': {},
        'car-parking': {},
        'point_isochrones': {'bike-parking': {}, 'car-parking': {}}
    })

    return travel_data

async def store_travel_time(
    mode: TransportModes,
    origin: Point,
    destination: Point,
    travel_time: float,
    travel_data: TravelData):
    """
    Asynchronously stores travel time between an origin and destination.

    Args:
        mode (TransportModes): Travel mode key.
        origin (Point): Start point.
        destination (Point): Destination point.
        travel_time (float): Duration in minutes.
        travel_data (TravelData): Currently stored data.
    """
    async with TravelDataLock:
        travel_data[mode]['isochrones'][origin] = {
            "destination": destination,
            "travel_time": travel_time
        }


async def store_point_travel_time(
    mode: TransportModes,
    center: Point,
    points: List[Point],
    travel_times: List[float],
    travel_data: TravelData):
    """
    Asynchronously stores travel times from a center point to a list of points.

    Args:
        mode (TransportModes): Transport mode.
        center (Point): Origin point.
        points (List[Point]): Destination points.
        travel_times (List[float]): Corresponding travel times.
        travel_data (TravelData): Data structure to store the result.
    """
    async with TravelDataLock:
        travel_data[mode]["point_isochrones"][center] = {
            "points": points,
            "travel_times": travel_times
        }