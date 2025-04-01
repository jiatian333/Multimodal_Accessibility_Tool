from variables import *

def mode_selection(mode):
    """Loads the mode template and replaces the mode placeholder."""
    
    with open(MODE_TEMPLATE, 'r', encoding='utf-8') as f:
        mode_xml = f.read()  # Read the file as a string
        
    return mode_xml.replace("${mode}", mode)
    

def select_parameters(rental = False):
    """Selects search parameters based on mode or rental requirement."""
    
    radius = 5000 if MODE == 'walk' or rental else 50000 if MODE in ['self-drive-car', 'car_sharing'] else 15000
        
    if rental:
        restriction_type = 'poi'
        with open(POI_TEMPLATE, 'r', encoding='utf-8') as f:
            poi_filter = f.read()  # Read the file as a string
            poi_filter = poi_filter.replace('${mode}', MODE)
    else:
        restriction_type, poi_filter = 'stop', ''
    
    return radius, restriction_type, poi_filter

def get_max_radius(mode):
    """Returns the maximum radius for a given mode."""
    
    mode_max_radius = {
        'walk': 1500,  # 1.5 km for walking
        'cycle': 3000,  # 5 km for bike
        'bicycle_rental': 3000,
        'escooter_rental': 3000,
        'self-drive-car': 6000, # 10 km for car
        'car_sharing': 6000 
    }
    
    return mode_max_radius.get(mode, 1000)

def params_distance_calculation(mode):
    mode_priority = {
        'rail': 2, 'TRAIN': 2, 'tram': 1, 'TRAM': 1, 'bus': 0, 'BUS': 0, 'suburbanRail': 1, 'urbanRail': 1, 'metro': 1,
        'underground': 1, 'coach': 0, 'water': 1, 'air': 2, 'telecabin': 0, 'funicular': 0,
        'taxi': 1, 'selfDrive': 1, 'unknown': 0, 'CABLE_RAILWAY': 0, 'CABLE_CAR': 0, 'METRO': 1, 'RACK_RAILWAY': 1, 'CHAIRLIFT': 0, 
        'BOAT': 1, 'ELEVATOR': 0, 'UNKNOWN': 0
    }
    
    base_max_distance = 300 if mode in ['car_sharing', 'self-drive-car'] else 200
    boost_factor = 0.05  # 5% extra per additional mode
    priority_boost_factor = 0.1  # 10% per highest priority mode
    weight_factor_base = 0.05  # Adjusts weighting effect
    
    return mode_priority, base_max_distance, boost_factor, priority_boost_factor, weight_factor_base

def r_tree_mode_map():
    
    mode_map = {
        "cycle": "bike-parking", "escooter_rental": "escooter-rental", "bicycle_rental": "bike-rental",
        "self-drive-car": "parking-facilities", "car_sharing": "car-rental", "public-transport": "public-transport"
    }
    
    return mode_map