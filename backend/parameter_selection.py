from variables import *

def mode_selection(mode):
    if MONO_MODE:
        with open(MODE_TEMPLATE, 'r', encoding='utf-8') as f:
            mode_xml = f.read()  # Read the file as a string
        mode_xml = mode_xml.replace("${mode}", mode)
    else:
        mode_xml = ''
        
    return mode_xml
    

def select_parameters(rental = False):
    if MODE in ['walk'] or rental: # Need to walk to rental stop; should not need to walk too much
        radius=5000
    elif MODE in ['self-drive-car', 'car_sharing']:
        radius=50000
    else:
        radius=15000
        
    if rental:
        restriction_type = 'poi'
        with open(POI_TEMPLATE, 'r', encoding='utf-8') as f:
            poi_filter = f.read()  # Read the file as a string
            poi_filter = poi_filter.replace('${mode}', MODE)
    else:
        restriction_type = 'stop'
        poi_filter=''
    
    return radius, restriction_type, poi_filter

def get_max_radius(mode):
    mode_max_radius = {
        'walk': 1500,  # 1.5 km for walking
        'cycle': 3000,  # 5 km for bike
        'bicycle_rental': 3000,
        'escooter_rental': 3000,
        'self-drive-car': 6000, # 10 km for car
        'car_sharing': 6000 
    }
    
    return mode_max_radius.get(mode, 1000)