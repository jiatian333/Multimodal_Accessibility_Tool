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
    if MODE in 'walk' or rental: # Need to walk to rental stop; should not need to walk too much
        radius=1000
    else:
        radius=5000
        
    if rental:
        restriction_type = 'poi'
        with open(POI_TEMPLATE, 'r', encoding='utf-8') as f:
            poi_filter = f.read()  # Read the file as a string
            poi_filter = poi_filter.replace('${mode}', MODE)
    else:
        restriction_type = 'stop'
        poi_filter=''
    
    return radius, restriction_type, poi_filter