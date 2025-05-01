"""
Spatial Sampling and Filtering Utilities

This module provides tools for:
- Generating random spatial points inside a polygon.
- Filtering spatial points based on a minimum distance threshold.

Functions:
----------
- random_points_in_polygon(...): Samples uniformly within a polygon.
- filter_close_points(...): Filters out points closer than a specified distance.

Returns:
--------
- List of `shapely.geometry.Point` objects, suitable for further spatial analysis.
"""

import logging
from typing import List, Union

import geopandas as gpd
import numpy as np
from pyproj import CRS
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon, MultiPolygon

from app.core.config import SEED

logger = logging.getLogger(__name__)

def random_points_in_polygon(
    polygon: Union[Polygon, MultiPolygon], 
    num_points: int
) -> List[Point]:
    """
    Generates uniformly distributed random points inside a polygon using rejection sampling.

    Args:
        polygon (Union[Polygon, MultiPolygon]): Geometry within which points are generated.
        num_points (int): Number of valid points to generate.

    Returns:
        List[Point]: List of Shapely Point objects inside the polygon.
    """
    np.random.seed(SEED)
    minx, miny, maxx, maxy = polygon.bounds
    points = []
    
    attempts = 0
    max_attempts = num_points*20

    while len(points) < num_points and attempts < max_attempts:
        remaining = num_points - len(points)
        rand_x = np.random.uniform(minx, maxx, remaining)
        rand_y = np.random.uniform(miny, maxy, remaining)
        candidates = [Point(x, y) for x, y in zip(rand_x, rand_y)]
        points.extend([p for p in candidates if polygon.contains(p)])
        attempts += 1
        
    if len(points) < num_points:
        logger.warning(f"Could not generate {num_points} points within polygon after {max_attempts} attempts.")

    return points


def filter_close_points(
    points: List[Point], 
    target_crs: CRS, 
    initial_crs: CRS, 
    min_dist: float = 50
) -> List[Point]:
    """
    Filters out points that are closer to each other than a given minimum distance.

    Args:
        points (List[Point]): Points to filter (assumed in initial_crs).
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        min_dist (float): Minimum allowed distance in meters (projected).

    Returns:
        List[Point]: Filtered list of points with sufficient spatial separation.
    """
    gdf = gpd.GeoDataFrame(geometry=points, crs=initial_crs).to_crs(target_crs)
    coords = np.array([[p.x, p.y] for p in gdf.geometry])
    tree = cKDTree(coords)
    
    mask = np.ones(len(coords), dtype=bool)
    for i in range(len(coords)):
        if not mask[i]:
            continue
        neighbors = tree.query_ball_point(coords[i], r=min_dist)
        neighbors = [n for n in neighbors if n > i]
        mask[neighbors] = False

    return list(np.array(points)[mask])