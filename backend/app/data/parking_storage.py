"""
Parking Data Management for Multimodal Travel

This module provides helper functions to store and retrieve parking location 
information associated with various transport modes in the `TravelData` structure.

Purpose:
--------
- Map transport modes to parking types ("bike-parking" or "car-parking").
- Read/write walking access times between stations and parking locations.
- Handle both standard and point-based isochrone parking data.

Functions:
----------
- `get_parking_type(mode)`: Maps a transport mode to its parking category.
- `get_stored_parking_info(...)`: Retrieves cached parking info if available.
- `store_parking(...)`: Stores new parking entries into the appropriate cache.

Usage:
------
Used during both network-wide and station-centered isochrone computations 
to manage walking access between travel nodes and parking infrastructure.

Example:
--------
    parking_type = get_parking_type("cycle")
    loc, time = get_stored_parking_info(travel_data, station, "cycle")
    travel_data = store_parking("cycle", station, parking, travel_data, time)
"""

import logging

from typing import Tuple, Union
from shapely.geometry import Point

from app.core.config import TravelDataLock, TransportModes
from app.core.data_types import TravelData

logger = logging.getLogger(__name__)

def get_parking_type(mode: TransportModes) -> str:
    """
    Maps a mode to its corresponding parking type.

    Args:
        mode (TransportModes): Transport mode.

    Returns:
        str: 'bike-parking' or 'car-parking', or '' if undefined.
    """
    parking_map = {
        'cycle': 'bike-parking',
        'bicycle_rental': 'bike-parking',
        'escooter_rental': 'bike-parking',
        'self-drive-car': 'car-parking',
        'car_sharing': 'car-parking'
    }
    parking_type = parking_map.get(mode, '')
    if not parking_type:
        logger.warning(f"No parking type defined for mode: {mode}")
    return parking_type


def get_stored_parking_info(
    travel_data: TravelData,
    point: Point,
    mode: TransportModes,
    point_isochrones: bool = False
) -> Union[Tuple[Point, float], Tuple[None, None]]:
    """
    Looks up cached parking access info for a given point and mode.

    Args:
        travel_data (TravelData): Cached data.
        point (Point): Query point.
        mode (TransportModes): Mode to get the appropriate parking type.
        point_isochrones (bool, optional): Whether to look in point-based storage.

    Returns:
        Union[Tuple[Point, float], Tuple[None, None]]: Parking location and walking time.
    """
    parking_type = get_parking_type(mode)
    
    entry = travel_data.get(parking_type, {}).get(point)
    if entry:
        logger.debug(f"Found stored parking={entry['parking']} for {mode} "
                     f"at point={point} (network isochrones storage).")
        return entry['parking'], entry['travel_time']
    
    if point_isochrones:
        entry = travel_data.get("point_isochrones", {}).get(parking_type, {}).get(point)
        if entry:
            logger.debug(f"Found stored parking={entry['parking']} for {mode} "
                         f"at point={point} (point isochrones storage).")
            return entry['parking'], entry['travel_time']

    return None, None


async def store_parking(
    mode: TransportModes,
    station: Point,
    parking: Point,
    travel_data: TravelData,
    walking_time: float,
    point_isochrones: bool = False):
    """
    Asynchronously stores parking data for a mode and point.

    Args:
        mode (TransportModes): Transport mode.
        station (Point): Station location.
        parking (Point): Parking location.
        travel_data (TravelData): Data structure.
        walking_time (float): Travel time from station to parking.
        point_isochrones (bool, optional): Whether to store under point-based key.
    """
    async with TravelDataLock:
        parking_type = get_parking_type(mode)
        storage = travel_data['point_isochrones'][parking_type] if point_isochrones else travel_data[parking_type]
        storage[station] = {'parking': parking, 'travel_time': walking_time}
        logger.debug(f"Stored parking for mode '{mode}' at point.")