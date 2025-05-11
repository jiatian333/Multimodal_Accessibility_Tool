"""
Adaptive Point Sampling for Urban Mobility Analysis

This module provides tools to generate spatial sample points based on:
- Road network intersection density
- Isochrone coverage
- Water-body exclusion

Functions:
----------
- filter_points_outside_water(...): Helper function that returns only valid points (inside polygon, outside water).
- generate_adaptive_sample_points(...): Refines grid samples using intersections and spatial constraints.
- sample_additional_points(...): Improves sampling coverage using isochrone and unsampled areas.

Returns:
--------
- List of `shapely.geometry.Point` in EPSG:4326 for consistent integration with travel data.
"""


import numpy as np
import geopandas as gpd
from shapely.geometry import Point, Polygon
from scipy.spatial import KDTree
from typing import List
from pyproj import CRS

from app.core.config import (
    SEED, EXTRA_POINTS, BASE_GRID_SIZE, DENSITY, TransportModes
)
from app.utils.calculate_intersections import save_and_load_intersections
from app.utils.mode_utils import get_graph
from app.sampling.filtering_points import (
    random_points_in_polygon, filter_close_points
)
from app.sampling.polygon_sampling import (
    extract_unsampled_area, identify_large_isochrones
)

def filter_points_outside_water(
    points: np.ndarray,
    polygon: Polygon,
    water_gdf: gpd.GeoDataFrame,
    target_crs: CRS
) -> np.ndarray:
    """
    Filters out points that intersect any water geometry or lie outside a polygon.

    Args:
        points (np.ndarray): Nx2 array of point coordinates (in target_crs).
        polygon (Polygon): Area to constrain sampling (in target_crs).
        water_gdf (GeoDataFrame): Water polygons (in target_crs).
        target_crs (CRS): CRS of the points and geometries.

    Returns:
        np.ndarray: 
            - Filtered point array
    """
    gdf = gpd.GeoDataFrame(geometry=[Point(p) for p in points], crs=target_crs)

    water_hits = gpd.sjoin(gdf, water_gdf, how="left", predicate="intersects")
    in_water_mask = water_hits.groupby(water_hits.index).first()["index_right"].notna()
    gdf["in_water"] = gdf.index.map(in_water_mask).fillna(False)

    valid_mask = gdf.geometry.within(polygon) & ~gdf["in_water"]
    return points[valid_mask.to_numpy()]

def generate_adaptive_sample_points(
    polygon: Polygon,
    water_gdf: gpd.GeoDataFrame,
    water_sindex: gpd.sindex.SpatialIndex,
    target_crs: CRS,
    initial_crs: CRS, 
    mode: TransportModes
) -> List[Point]:
    """
    Generates a spatially adaptive set of sample points within the city polygon,
    avoiding water areas and leveraging intersection density for refinement.

    Args:
        polygon (Polygon): City boundary (EPSG:4326).
        water_gdf (GeoDataFrame): Projected water bodies for spatial filtering (in target_crs).
        water_sindex (gpd.sindex.SpatialIndex): Spatial index for water_gdf.
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        mode (TransportModes): Transport mode (e.g., 'walk', 'cycle', 'car_sharing').

    Returns:
        List[Point]: Filtered and distributed spatial sample points (EPSG:4326).
    """
    np.random.seed(SEED)
    polygon = gpd.GeoSeries(polygon, crs=initial_crs).to_crs(target_crs).iloc[0]
    
    network_type, graph_city, _ = get_graph(mode)

    if EXTRA_POINTS > 0:
        intersection_dict = save_and_load_intersections(
            network_type, target_crs, polygon, water_gdf, 
            water_sindex, BASE_GRID_SIZE, DENSITY, graph_city
        )
        intersection_counts = np.array(intersection_dict[network_type][BASE_GRID_SIZE], dtype=float)

    minx, miny, maxx, maxy = polygon.bounds
    x_vals, y_vals = np.meshgrid(
        np.linspace(minx, maxx, int(np.ceil((maxx - minx) / BASE_GRID_SIZE))),
        np.linspace(miny, maxy, int(np.ceil((maxy - miny) / BASE_GRID_SIZE)))
    )
    x_vals, y_vals = x_vals.flatten(), y_vals.flatten()
    points = np.column_stack((x_vals, y_vals)) + BASE_GRID_SIZE / 2

    random_offsets = np.random.uniform(-BASE_GRID_SIZE / 3, BASE_GRID_SIZE / 3, points.shape)
    points += random_offsets
    
    valid_points = filter_points_outside_water(points, polygon, water_gdf, target_crs)

    if EXTRA_POINTS > 0 and intersection_counts.sum() > 0:
        valid_indices = np.where(intersection_counts > 0)[0]
        valid_weights = np.log(intersection_counts[valid_indices])
        valid_weights /= valid_weights.sum()

        extra_indices = np.random.choice(valid_indices, EXTRA_POINTS, p=valid_weights)
        extra_offsets = np.random.uniform(-BASE_GRID_SIZE / 2, BASE_GRID_SIZE / 2, (EXTRA_POINTS, 2))
        extra_points = np.column_stack((x_vals[extra_indices], y_vals[extra_indices])) + BASE_GRID_SIZE / 2 + extra_offsets

        valid_extra_points = filter_points_outside_water(extra_points, polygon, water_gdf, target_crs)
        valid_points = np.vstack((valid_points, valid_extra_points))

    tree = KDTree(valid_points)
    pairs = tree.query_pairs(r=100)
    clusters = {i: set([i]) for i in range(len(valid_points))}
    
    for i, j in pairs:
        clusters[i].add(j)
        clusters[j].add(i)

    keep_points = set(range(len(valid_points)))
    for cluster in clusters.values():
        if len(cluster) > 1:
            keep_points -= cluster
            keep_points.add(np.random.choice(list(cluster)))

    final_points = valid_points[list(keep_points)]
    gdf_points = gpd.GeoDataFrame(geometry=[Point(p) for p in final_points], crs=target_crs)
    return gdf_points.to_crs(initial_crs).geometry.tolist()


def sample_additional_points(
    isochrones_gdf: gpd.GeoDataFrame,
    city_polygon: Polygon,
    water_gdf: gpd.GeoDataFrame,
    target_crs: CRS, 
    initial_crs: CRS, 
    n_unsampled: int = 50,
    n_large_isochrones: int = 50
) -> List[Point]:
    """
    Identify unsampled regions and large isochrone zones to generate extra sample points.

    Args:
        isochrones_gdf (GeoDataFrame): Existing isochrones to evaluate coverage.
        city_polygon (Polygon): Area to constrain the sampling.
        water_gdf (GeoDataFrame): Individual water features (e.g., rivers, lakes).
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        n_unsampled (int): Number of points to distribute in uncovered areas.
        n_large_isochrones (int): Number of points to spread across large isochrones.

    Returns:
        List[Point]: List of additional sampled points (in EPSG:4326).
    """
    additional_points: List[Point] = []

    unsampled_area = extract_unsampled_area(city_polygon, water_gdf, isochrones_gdf)
    if not unsampled_area.is_empty:
        areas_to_sample = list(unsampled_area.geoms) if unsampled_area.geom_type == 'MultiPolygon' else [unsampled_area]
        total_area = sum(area.area for area in areas_to_sample)
        for area in areas_to_sample:
            if total_area == 0: break
            weight = int(n_unsampled * (area.area / total_area))
            additional_points.extend(random_points_in_polygon(area, weight))

    large_isochrones = identify_large_isochrones(isochrones_gdf, target_crs, initial_crs)
    if large_isochrones:
        total_iso_area = sum(iso.area for iso in large_isochrones)
        for iso in large_isochrones:
            if total_iso_area == 0: break
            weight = int(n_large_isochrones * (iso.area / total_iso_area))
            additional_points.extend(random_points_in_polygon(iso, weight))

    return filter_close_points(additional_points, target_crs, initial_crs, min_dist=150)