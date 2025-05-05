"""
Transport Mode Parameter Selection Utilities

This module defines configuration strategies and adaptive thresholds for routing and spatial queries,
based on mode of transport and performance preferences.

Functions
---------
- mode_selection: Embeds a transport mode into an OJP XML request template.
- get_travel_mode_and_xml: Maps high-level mode to physical routing mode.
- select_parameters: Returns radius, restriction type, and POI filters for spatial queries.
- get_max_radius: Chooses a clipping/search radius based on transport mode and performance setting.
- params_distance_calculation: Returns scoring and weighting parameters for multi-modal routing.
- get_graph: Returns pre-computed graphs depending on the mode. Used either during intersection calculation or routing. 

Returns
-------
Various constants used during major parts of the backend.
"""


import logging
from typing import Dict, Tuple

from networkx import MultiDiGraph

from app.core.cache import stationary_data
from app.core.config import MODE_TEMPLATE, POI_TEMPLATE, TransportModes

logger = logging.getLogger(__name__)

def mode_selection(mode: TransportModes) -> str:
    """
    Loads and fills a mode template for use in XML OJP trip requests.

    Args:
        mode (TransportModes): Mode of transport to embed into the XML template.

    Returns:
        str: XML snippet with the mode inserted.
    """
    try:
        with open(MODE_TEMPLATE, 'r', encoding='utf-8') as f:
            mode_xml = f.read()
    except FileNotFoundError as e:
        logger.error(f"Missing XML mode template: {MODE_TEMPLATE}")
        raise e

    return mode_xml.replace("${mode}", mode)
    
def get_travel_mode_and_xml(mode: TransportModes) -> Tuple[TransportModes, str]:
    """
    Maps rental-style modes to physical travel behavior and resolves OJP tag.

    Converts rental modes to their private analog (e.g. cycling, driving).
    Used to identify the proper routing behavior and mode selection in OJP queries.

    Args:
    mode (TransportModes): Logical transport mode (may be rental or walk).

    Returns:
        Tuple[str, str]: A tuple containing:
            - The internal routing mode (e.g., 'cycle')
            - The OJP XML routing keyword used in API queries
    """
    travel_mode = {
        'car_sharing': 'self-drive-car',
        'bicycle_rental': 'cycle',
        'escooter_rental': 'cycle'
    }.get(mode, mode)
    return travel_mode, mode_selection(travel_mode)

def select_parameters(
    mode: TransportModes, 
    rental: bool = False
) -> Tuple[int, str, str]:
    """
    Selects search parameters such as radius, restriction type, and POI filter
    based on the given transport mode and rental status.

    Args:
        mode (TransportModes): Mode of transport (e.g., 'walk', 'cycle', 'car_sharing').
        rental (bool, optional): If true, parameters are adapted for rental station search.

    Returns:
        Tuple[int, str, str]: (radius, restriction_type, poi_filter)
    """
    if rental:
        radius = 5000
        restriction_type = "poi"
        
        try:
            with open(POI_TEMPLATE, 'r', encoding='utf-8') as f:
                poi_filter = f.read().replace("${mode}", mode)
        except FileNotFoundError as e:
            logger.error(f"Missing POI template: {POI_TEMPLATE}")
            raise e
    else:
        restriction_type, poi_filter = "stop", ""
        radius = {
            "walk": 5000,
            "self-drive-car": 50000,
            "car_sharing": 50000
        }.get(mode, 15000)
        
    return radius, restriction_type, poi_filter

def get_max_radius(mode: TransportModes, performance: bool) -> int:
    """
    Returns a performance-dependent max radius for point selection and isochrone clipping.

    Args:
        mode (TransportModes): Mode of transport.
        performance (bool): Reduce radius for faster execution.

    Returns:
        int: Maximum radius in meters.
    """
    if performance:
        limits = {
            "walk": 1500,
            "cycle": 2500,
            "bicycle_rental": 2500,
            "escooter_rental": 2500,
            "self-drive-car": 5000,
            "car_sharing": 5000
        }
    else:
        limits = {
            "walk": 2000,
            "cycle": 7500,
            "bicycle_rental": 7500,
            "escooter_rental": 7500,
            "self-drive-car": 10000,
            "car_sharing": 10000
        }

    return limits.get(mode, 1500)

def params_distance_calculation(mode: TransportModes) -> Tuple[Dict[str, int], int, float, float, float, float]:
    """
    Defines scoring weights and distance factors for multi-modal prioritization.

    Args:
        mode (TransportModes): Current mode of transport.

    Returns:
        Tuple:
            - mode_priority (dict): Scoring per transport mode.
            - base_max_distance (int): Distance limit in meters.
            - boost_factor (float): Boost per additional mode.
            - priority_boost_factor (float): Boost per highest-priority mode.
            - weight_factor_base (float): General multiplier for weighting.
            - weight_mode (float): Scaling for travel distance from origin.
    """
    mode_priority = {
        'rail': 2, 'TRAIN': 2, 'tram': 1, 'TRAM': 1, 'bus': 0, 'BUS': 0, 'suburbanRail': 1, 
        'urbanRail': 1, 'metro': 1, 'underground': 1, 'coach': 0, 'water': 1, 'air': 2, 
        'telecabin': 0, 'funicular': 0, 'taxi': 1, 'selfDrive': 1, 'unknown': 0, 
        'CABLE_RAILWAY': 0, 'CABLE_CAR': 0, 'METRO': 1, 'RACK_RAILWAY': 1, 'CHAIRLIFT': 0, 
        'BOAT': 1, 'ELEVATOR': 0, 'UNKNOWN': 0
    }

    base_max_distance = 800 if mode in ['car_sharing', 'self-drive-car'] else 600
    boost_factor = 0.05               # +5% allowed distance for each extra available mode
    priority_boost_factor = 0.10      # +10% for highest-priority modes (e.g., TRAIN)
    weight_factor_base = 0.05         # General scaling factor
    
    weight_mode = 0.5 if mode in ['car_sharing', 'self-drive-car'] else 0.7

    return (
        mode_priority, 
        base_max_distance, 
        boost_factor, 
        priority_boost_factor, 
        weight_factor_base,
        weight_mode
    )
    
def get_graph(mode: TransportModes) -> Tuple[str, MultiDiGraph, MultiDiGraph]:
    """
    Selects the appropriate city and canton graphs based on transport mode.

    Args:
        mode (TransportModes): Requested mode of travel.

    Returns:
        Tuple[str, MultiDiGraph, MultiDiGraph]: 
            - Network type ("walk", "bike", "drive"),
            - City graph (MultiDiGraph),
            - Canton graph (MultiDiGraph).
    """
    network_type = {
        'cycle': 'bike',
        'bicycle_rental': 'bike',
        'escooter_rental': 'bike',
        'self-drive-car': 'drive',
        'car_sharing': 'drive'
    }.get(mode, 'walk')
    
    if network_type == 'bike':
        return network_type, stationary_data.G_bike_city, stationary_data.G_bike_canton
    elif network_type == 'drive':
        return network_type, stationary_data.G_car_city, stationary_data.G_car_canton
    return network_type, stationary_data.G_city, stationary_data.G_canton
