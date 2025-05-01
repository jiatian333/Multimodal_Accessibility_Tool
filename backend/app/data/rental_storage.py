"""
Rental Station Management for Multimodal Travel Data

This module handles storage and retrieval of rental station data 
in the `TravelData` cache for both network-wide and point-based 
isochrone calculations.

Purpose:
--------
- Track nearest rental stations (walking access) from any destination.
- Track travel time from a rental station to the best reachable location.
- Retrieve riding-phase travel time: rental station → rental station of closest destination.
- Maintain mode-specific caches for accurate and fast lookup.

Functions:
----------
- `get_stored_closest_rental(...)`: Get nearest rental station + walk time.
- `store_closest_rental(...)`: Cache nearest rental access point + walk time.
- `get_stored_rental_station_info(...)`: Get destination and riding time from a rental station.
- `store_rental_station_info(...)`: Cache riding phase (station → destination).

Features:
---------
- Handles both isochrone strategies: full-network & station-centered.
- Supports bike rental, escooter rental, and car sharing.
- Ensures data consistency by storing separately for each mode & type.

Usage:
------
    station, walk_time = get_stored_closest_rental(travel_data, "bicycle_rental", point)
    travel_data = store_closest_rental(travel_data, "bicycle_rental", point, station, walk_time)
    travel_data = store_rental_station_info(station, dest, ride_time, "bicycle_rental", travel_data)
"""


import logging
from typing import Tuple, Union

from shapely.geometry import Point
from app.core.config import TravelDataLock, TransportModes
from app.core.data_types import TravelData

logger = logging.getLogger(__name__)

def get_stored_closest_rental(
    travel_data: TravelData,
    mode: TransportModes,
    destination: Point,
    point_isochrones: bool = False
) -> Union[Tuple[Point, float], Tuple[None, None]]:
    """
    Retrieves closest rental station and walking time from cache.

    Args:
        travel_data (TravelData): Cached travel data.
        mode (TransportModes): Mode to query.
        destination (Point): Point for which data is requested.
        point_isochrones (bool, optional): Check point-based data if True.

    Returns:
        Union[Tuple[Point, float], Tuple[None, None]]: Rental point and time.
    """
    station_data = travel_data.get(mode, {}).get("station_rental", {})
    
    entry = station_data.get("isochrones", {}).get(destination)
    if entry:
        logger.debug(f"Retrieved closest rental station={entry['nearest_rental']} "
                    f"to destination={destination} for mode={mode} (network isochrones storage)")
        return entry['nearest_rental'], entry['travel_time']
    
    if point_isochrones:
        entry = station_data.get("point_isochrones", {}).get(destination)
        if entry:
            logger.debug(f"Retrieved closest rental station={entry['nearest_rental']} "
                    f"to destination={destination} for mode={mode} (point isochrones storage)")
            return entry['nearest_rental'], entry['travel_time']

    return None, None


async def store_closest_rental(
    travel_data: TravelData,
    mode: TransportModes,
    destination: Point,
    rental_station: Point,
    walking_time: float,
    point_isochrones: bool = False):
    """
    Asynchronously caches nearest rental station and walk time for a destination.

    Args:
        travel_data (TravelData): Target data dictionary.
        mode (TransportModes): Rental mode (e.g. bicycle_rental).
        destination (Point): Target point.
        rental_station (Point): Closest rental station.
        walking_time (float): Travel time from station to destination.
        point_isochrones (bool, optional): Whether to store under point-based lookup.
    """
    async with TravelDataLock:
        key = "point_isochrones" if point_isochrones else "isochrones"
        storage = travel_data[mode]['station_rental'][key]
        storage[destination] = {
            'nearest_rental': rental_station,
            'travel_time': walking_time
        }
        logger.debug(f"Stored closest rental for mode '{mode}' at point.")

def get_stored_rental_station_info(
    travel_data: TravelData,
    mode: TransportModes,
    rental_station: Point
) -> Union[Tuple[Point, float], Tuple[None, None]]:
    """
    Retrieves destination and riding time from a given rental station using cache (only used for network isochrones).
    Travel time is between the first and last rental station using the corresponding mode.

    Args:
        travel_data (TravelData): Cached travel data structure.
        mode (TransportModes): Rental mode (e.g. bicycle_rental, car_sharing).
        rental_station (Point): Station from which the trip starts.

    Returns:
        Union[Tuple[Point, float], Tuple[None, None]]:
            Tuple of (destination point, riding time in minutes), or (None, None) if not cached.
    """
    rental_data = travel_data.get(mode, {}).get("rental", {})
    info = rental_data.get(rental_station)

    if info and "travel_time" in info and "nearest" in info:
        logger.debug(f"Retrieved closest rental station={info['nearest']} "
                    f"to starting rental station={rental_station} for mode={mode}")
        return info["nearest"], info["travel_time"]

    return None, None

async def store_rental_station_info(
    rental_station: Point,
    nearest_dest: Point,
    riding_time: float,
    mode: TransportModes,
    travel_data: TravelData):
    """
    Asynchronously stores info for a rental station (only used for network isochrones): 
    destination and riding time to the rental station that is closest to the destination

    Args:
        rental_station (Point): Origin rental station.
        nearest_dest (Point): Closest destination reached from rental.
        riding_time (float): Duration of rental ride (in minutes).
        mode (TransportModes): Mode of transport.
        travel_data (TravelData): Current data.
    """
    async with TravelDataLock:
        travel_data[mode]['rental'][rental_station] = {
            "nearest": nearest_dest,
            "travel_time": riding_time
        }
        logger.debug(f"Stored rental riding time from origin rental station for mode '{mode}'.")