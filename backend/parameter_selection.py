#!/usr/bin/env python
# coding: utf-8

from variables import MODE_TEMPLATE, POI_TEMPLATE

def mode_selection(mode):
    """Loads the mode template and replaces the mode placeholder."""
    
    with open(MODE_TEMPLATE, 'r', encoding='utf-8') as f:
        mode_xml = f.read()  # Read the file as a string
        
    return mode_xml.replace("${mode}", mode)
    

def select_parameters(mode, rental = False):
    """Selects search parameters based on mode or rental requirement."""
    
    radius = 5000 if mode == 'walk' or rental else 50000 if mode in ['self-drive-car', 'car_sharing'] else 15000
        
    if rental:
        restriction_type = 'poi'
        with open(POI_TEMPLATE, 'r', encoding='utf-8') as f:
            poi_filter = f.read()  # Read the file as a string
            poi_filter = poi_filter.replace('${mode}', mode)
    else:
        restriction_type, poi_filter = 'stop', ''
    
    return radius, restriction_type, poi_filter

def get_max_radius(mode, performance):
    """Returns the maximum radius for a given mode."""
    
    if performance:
        return {
            'walk': 1500,
            'cycle': 2500,
            'bicycle_rental': 2500,
            'escooter_rental': 2500,
            'self-drive-car': 5000,
            'car_sharing': 5000 
        }.get(mode, 1500)
        
    else:
        return {
        'walk': 5000,
        'cycle': 5000,
        'bicycle_rental': 7500,
        'escooter_rental': 7500,
        'self-drive-car': 10000,
        'car_sharing': 10000 
    }.get(mode, 5000)

def params_distance_calculation(mode):
    mode_priority = {
        'rail': 2, 'TRAIN': 2, 'tram': 1, 'TRAM': 1, 'bus': 0, 'BUS': 0, 'suburbanRail': 1, 'urbanRail': 1, 'metro': 1,
        'underground': 1, 'coach': 0, 'water': 1, 'air': 2, 'telecabin': 0, 'funicular': 0,
        'taxi': 1, 'selfDrive': 1, 'unknown': 0, 'CABLE_RAILWAY': 0, 'CABLE_CAR': 0, 'METRO': 1, 'RACK_RAILWAY': 1, 'CHAIRLIFT': 0, 
        'BOAT': 1, 'ELEVATOR': 0, 'UNKNOWN': 0
    }
    
    base_max_distance = 400 if mode in ['car_sharing', 'self-drive-car'] else 300
    boost_factor = 0.05  # 5% extra per additional mode
    priority_boost_factor = 0.1  # 10% per highest priority mode
    weight_factor_base = 0.05  # Adjusts weighting effect
    
    return mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base