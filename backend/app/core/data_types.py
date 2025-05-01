"""
Typed Data Structures for Multimodal Isochrone Computation

This module defines the `TypedDict`-based data contracts used across the 
isochrone pipeline. These structures standardize how travel times, routing data, 
parking access, and rental information are stored, cached, and processed.

Purpose:
--------
- Ensure type safety and IDE support across the multimodal computation flow.
- Define reusable schemas for travel data caching and serialization.
- Improve consistency across API response shaping, persistence, and internal logic.

Key Structures:
---------------
- `IsochroneEntry` / `PointIsochroneEntry`: Represent travel time from/to destinations.
- `ParkingEntry`: Captures walk access time to/from a parking location.
- `RentalAccessEntry` / `RentalRidingEntry`: Represent walking and riding phases of a rental.
- `StationRentalData`: Contains both network and point-origin rental lookup tables.
- `TravelDataMode`: Represents travel info for a single transport mode.
- `TravelData`: The top-level structure aggregating all per-mode data and parking info.
- `StationDict`: Flat location record used for simple serialization.

Usage:
------
These types are used to enforce structure in cache files, intermediate results,
and endpoint responses:

    from app.core.data_types import TravelData
    travel_data: TravelData = load_data()
    walk_time = travel_data["walk"]["isochrones"][some_point]["travel_time"]

Notes:
------
- These are used as **non-enforced typing helpers** and will not raise at runtime.
- All `Point` keys are expected to be serialized via WKT or GeoJSON if persisted.
"""



from typing import Dict, List, TypedDict
from shapely.geometry import Point

class IsochroneEntry(TypedDict):
    """
    Represents a travel connection from an origin to a destination.

    Attributes:
        destination (Point): Destination point reached from the origin.
        travel_time (float): Travel time in minutes.
    """
    destination: Point
    travel_time: float


class PointIsochroneEntry(TypedDict):
    """
    Represents multiple reachable destinations from one origin.

    Attributes:
        points (List[Point]): List of reachable destinations.
        travel_times (List[float]): Corresponding travel times in minutes.
    """
    points: List[Point]
    travel_times: List[float]


class ParkingEntry(TypedDict):
    """
    Caches a parking spot and walking time from/to a station.

    Attributes:
        parking (Point): Location of the parking facility.
        travel_time (float): Walking time in minutes.
    """
    parking: Point
    travel_time: float


class RentalRidingEntry(TypedDict):
    """
    Represents the riding phase of a rental trip.

    Attributes:
        nearest (Point): Destination reachable from rental station.
        travel_time (float): Travel time between the rental station and destination.
    """
    nearest: Point
    travel_time: float


class RentalAccessEntry(TypedDict):
    """
    Represents access from a destination to the nearest rental station.

    Attributes:
        nearest_rental (Point): Nearest rental station.
        travel_time (float): Walking time from destination to station.
    """
    nearest_rental: Point
    travel_time: float


class StationRentalData(TypedDict):
    """
    Stores rental station access data in two modes:
    - `isochrones`: For network-based isochrone computation
    - `point_isochrones`: For point-based origin center isochrones

    Attributes:
        isochrones (Dict[Point, RentalAccessEntry]):
            Nearest rental station for each destination (network-based).
        point_isochrones (Dict[Point, RentalAccessEntry]):
            Same as above but for center-based sampling.
    """
    isochrones: Dict[Point, RentalAccessEntry]
    point_isochrones: Dict[Point, RentalAccessEntry]

class TravelDataMode(TypedDict, total=False):
    """
    Travel metadata per transport mode.

    Fields vary by whether the mode supports rental or not.

    Attributes:
        isochrones (Dict[Point, IsochroneEntry]):
            Single-destination isochrones for network-based points.
        point_isochrones (Dict[Point, PointIsochroneEntry]):
            Multi-destination isochrones from a single point.
        rental (Dict[Point, RentalRidingEntry]):
            Rental riding phase — from rental station to best reachable destination.
            Only for modes: bicycle_rental, escooter_rental, car_sharing.
        station_rental (StationRentalData):
            Access phase — from destination to nearest rental station.
            Only for modes: bicycle_rental, escooter_rental, car_sharing.
    """
    isochrones: Dict[Point, IsochroneEntry]
    point_isochrones: Dict[Point, PointIsochroneEntry]
    rental: Dict[Point, RentalRidingEntry]
    station_rental: StationRentalData


class TravelData(TypedDict, total=False):
    """
    Main container for all travel and parking data.

    Attributes:
        walk, cycle, self_drive_car, bicycle_rental, escooter_rental, car_sharing (TravelDataMode):
            Per-mode metadata. Only rental-based modes contain 'rental' and 'station_rental'.
        bike_parking, car_parking (Dict[Point, ParkingEntry]):
            Parking information per station.
        point_isochrones (Dict[str, Dict[Point, ParkingEntry]]):
            Point-based parking data for 'bike-parking' or 'car-parking'.
    """
    
    __annotations__ = {
        'walk': TravelDataMode,
        'cycle': TravelDataMode,
        'self-drive-car': TravelDataMode,
        'bicycle_rental': TravelDataMode,
        'escooter_rental': TravelDataMode,
        'car_sharing': TravelDataMode,
        'bike-parking': Dict[Point, ParkingEntry],
        'car-parking': Dict[Point, ParkingEntry],
        'point_isochrones': Dict[str, Dict[Point, ParkingEntry]]
    }


class StationDict(TypedDict):
    """
    Simple flat representation of a station location.

    Attributes:
        lon (float): Longitude.
        lat (float): Latitude.
    """
    lon: float
    lat: float