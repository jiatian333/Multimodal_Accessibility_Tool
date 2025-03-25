#!/usr/bin/env python
# coding: utf-8
from variables import DENSITY_DATA_PATH, NETWORK_AREA

import pickle
import os
import numpy as np
from shapely.geometry import Polygon
import osmnx as ox
import pyproj

def calculate_intersections_per_grid(graph, nodes, polygon, water_union, river_union, grid_size=500):
    """
    Calculate the intersection density for a given graph, nodes, and grid structure.
    
    Args:
        G (networkx.Graph): The transportation graph.
        nodes (GeoDataFrame): The nodes in the transportation graph.
        polygon (shapely.geometry.Polygon): The city boundary polygon.
        grid_size (int): The size of the grid (in meters).
        mode (str): The mode of transportation ('walk', 'bike', or 'drive').

    Returns:
        list: List of intersection densities for each grid cell.
    """
    
    # Precompute intersection nodes based on degree
    intersections = [idx for idx, deg in graph.degree() if deg > 2]

    # **Step 1: Define the grid**
    minx, miny, maxx, maxy = polygon.bounds
    x_vals = np.linspace(minx, maxx, int(np.ceil((maxx - minx) / grid_size)))
    y_vals = np.linspace(miny, maxy, int(np.ceil((maxy - miny) / grid_size)))

    # Precompute intersection densities
    total_grid_intersections = []
    

    # Iterate over the grid
    for x_start in x_vals:
        for y_start in y_vals:
            # Define the bounding box of the current grid
            grid_polygon = Polygon([(x_start, y_start),
                                    (x_start + grid_size, y_start),
                                    (x_start + grid_size, y_start + grid_size),
                                    (x_start, y_start + grid_size)])

            # Ensure the grid is inside the city boundary
            if not polygon.intersects(grid_polygon):
                continue

            # Find intersections within this grid
            grid_intersections = 0

            for idx in intersections:
                node_point = nodes.loc[idx, 'geometry']
                
                # If node is inside the grid and does not intersect with water or river
                if grid_polygon.intersects(node_point) and not water_union.intersects(node_point) and not river_union.intersects(node_point):
                    grid_intersections+=1
            
            total_grid_intersections.append(grid_intersections)

    return total_grid_intersections


def save_and_load_intersections(mode, target_crs, polygon, water_gdf, river_gdf, grid_size=500, filename=DENSITY_DATA_PATH):
    """
    Load or save the intersection density calculations to a pickle file.
    
    Args:
        mode (str): The transport mode ('walk', 'bike', 'drive').
        grid_size (int): The size of the grid (in meters).
        filename (str): The name of the pickle file to load/save the results.
    
    Returns:
        dict: Updated intersection density dictionary.
    """
    if os.path.exists(filename):
        with open(filename, 'rb') as f:
            intersection_density_dict = pickle.load(f)
    else:
        intersection_density_dict = {}
    
    if mode in intersection_density_dict and grid_size in intersection_density_dict[mode]:
        print(f"Intersections per grid for {mode} is already calculated. Returning saved data.")
        return intersection_density_dict
    
    elif mode not in intersection_density_dict:
        intersection_density_dict[mode] = {}
    graph = ox.graph_from_place(NETWORK_AREA, network_type=mode)
    nodes, _ = ox.graph_to_gdfs(graph)
    nodes = nodes.to_crs(target_crs)

    # For each grid size (e.g., 500m x 500m, 1000m x 1000m), calculate densities
    intersection_density_dict[mode][grid_size] = calculate_intersections_per_grid(
        graph, nodes, polygon, water_gdf, river_gdf, grid_size)
    
    print(f'Successfully calculated intersections per grid for mode: {mode}')

    # Save the dictionary to a pickle file
    with open(filename, 'wb') as f:
        pickle.dump(intersection_density_dict, f)
    
    return intersection_density_dict