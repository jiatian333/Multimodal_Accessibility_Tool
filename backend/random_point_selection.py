from variables import *

import geopandas as gpd
import random
from shapely.geometry import Point
import osmnx as ox

def extract_polygon_and_generate_points(num_points=10):
    random.seed(SEED)
    gdf = ox.geocode_to_gdf(NETWORK_AREA)
    
    if gdf.empty:
        raise ValueError("No polygon found for the city of Zurich")
    
    # Fetch water bodies from OpenStreetMap
    water_gdf = ox.features_from_place(NETWORK_AREA, tags={"natural": "water"})
    river_gdf = ox.features_from_place(NETWORK_AREA, tags={"waterway": True})
    
    # Merge water features into a single MultiPolygon
    water_union = water_gdf.unary_union
    river_union = river_gdf.unary_union
    
    # Extract the first polygon (assuming one match)
    polygon = gdf.geometry.iloc[0]
    
    # Generate random points within the polygon
    points = []
    minx, miny, maxx, maxy = polygon.bounds
    
    while len(points) < num_points:
        random_point = Point(
            random.uniform(minx, maxx), 
            random.uniform(miny, maxy)
        )
        
        if (
            polygon.contains(random_point) and 
            not water_union.contains(random_point) and 
            not river_union.contains(random_point)
        ):
            points.append(random_point)
    
    return points