"""
Grid-Based Intersection Density Analysis

This module calculates intersection densities over a regular grid for a given
transportation network and saves the results for reuse.

Functions
---------
- calculate_intersections_per_grid(...): Counts node intersections per square grid cell.
- save_and_load_intersections(...): Loads or calculates cached densities per transport mode.

Returns
-------
- List[int]: Grid-wise intersection counts.
- Dict[str, Dict[int, List[int]]]: Nested structure of intersection densities by mode and grid size.
"""



import logging
import pickle
from pathlib import Path
from typing import Dict, List

import networkx as nx
import numpy as np
import osmnx as ox
from geopandas import GeoDataFrame, sindex
from shapely.geometry import Polygon
from pyproj import CRS

logger = logging.getLogger(__name__)

def calculate_intersections_per_grid(
    graph: nx.MultiDiGraph,
    nodes: GeoDataFrame,
    polygon: Polygon,
    water_gdf: GeoDataFrame,
    water_sindex: sindex.SpatialIndex,
    grid_size: int = 500
) -> List[int]:
    """
    Calculate the intersection count per grid cell for a given transport graph.

    Args:
        graph (nx.MultiDiGraph): The transportation network graph.
        nodes (GeoDataFrame): GeoDataFrame containing node geometries.
        polygon (Polygon): The bounding polygon.
        water_gdf (GeoDataFrame): Projected water bodies to exclude intersections.
        water_sindex (sindex.SpatialIndex): Spatial index for water_gdf.
        grid_size (int, optional): Size of the square grid cells in meters. Default is 500.

    Returns:
        List[int]: Intersection counts for each grid cell that overlaps the polygon boundary.
    """
    intersections = {idx for idx, deg in graph.degree() if deg > 2}

    minx, miny, maxx, maxy = polygon.bounds
    x_vals = np.linspace(minx, maxx, int(np.ceil((maxx - minx) / grid_size)))
    y_vals = np.linspace(miny, maxy, int(np.ceil((maxy - miny) / grid_size)))

    total_grid_intersections: List[int] = []

    for x_start in x_vals:
        for y_start in y_vals:
            grid_polygon = Polygon([
                (x_start, y_start),
                (x_start + grid_size, y_start),
                (x_start + grid_size, y_start + grid_size),
                (x_start, y_start + grid_size)
            ])

            if not polygon.intersects(grid_polygon):
                continue

            grid_intersections = 0
            for idx in intersections:
                point = nodes.loc[idx, 'geometry']
                if not grid_polygon.contains(point):
                    continue
                hits = list(water_sindex.intersection(point.bounds))
                if not hits or not water_gdf.iloc[hits].intersects(point).any():
                    grid_intersections += 1

            total_grid_intersections.append(grid_intersections)

    return total_grid_intersections


def save_and_load_intersections(
    mode: str,
    target_crs: CRS,
    polygon: Polygon,
    water_gdf: GeoDataFrame,
    water_sindex: sindex.SpatialIndex,
    grid_size: int,
    filename: Path,
    graph: nx.MultiDiGraph
) -> Dict[str, Dict[int, List[int]]]:
    """
    Load or calculate and save intersection density data for a given mode and grid size.

    Args:
        mode (str): Transport mode ('walk', 'bike', 'drive').
        target_crs (CRS): Target coordinate reference system for projection.
        polygon (Polygon): City boundary polygon.
        water_gdf (GeoDataFrame): Individual water features.
        water_sindex (sindex.SpatialIndex): Spatial index for water_gdf.
        grid_size (int): Size of grid cells in meters.
        filename (Path): Path to pickle file for saving/loading intersection data.
        graph (nx.MultiDiGraph): Graph of the city area, varies depending on the mode.

    Returns:
        Dict[str, Dict[int, List[int]]]: Nested dictionary containing intersection counts.
    """
    intersection_data: Dict[str, Dict[int, List[int]]] = {}

    if filename.exists():
        try:
            with open(filename, "rb") as f:
                intersection_data = pickle.load(f)
        except (pickle.UnpicklingError, EOFError) as e:
            logger.warning(f"Failed to load pickle at {filename}: {e}. Recomputing.")

    if mode in intersection_data and grid_size in intersection_data[mode]:
        logger.info(f"[Cache] Returning cached intersections for mode '{mode}' and grid size {grid_size}")
        return intersection_data

    intersection_data.setdefault(mode, {})
    nodes, _ = ox.graph_to_gdfs(graph)
    nodes = nodes.to_crs(target_crs)

    intersection_data[mode][grid_size] = calculate_intersections_per_grid(
        graph, nodes, polygon, water_gdf, water_sindex, grid_size
    )

    try:
        with open(filename, "wb") as f:
            pickle.dump(intersection_data, f)
        logger.info(f"Saved intersection data to {filename}")
    except Exception as e:
        logger.error(f"Failed to save intersection data: {e}")

    return intersection_data