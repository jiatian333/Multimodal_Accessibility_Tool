"""
Isochrone Generation and Contour Extraction

This module provides the full pipeline for generating isochrones from spatial travel time data.
It supports both network-wide and point-centered isochrones and handles raster interpolation,
geometry extraction, and projection management. Note that some stages are skipped if the 
performance mode is toggled accordingly. 

Processing Stages:
------------------
1. Extract known travel time samples from `TravelData`.
2. Perform IDW interpolation over a 2D grid.
3. Smooth and fill gaps in the resulting grid.
4. Extract binary contours per travel time level.
5. Polygonize and clip contours against city boundaries (minus water).
6. Return results as a GeoDataFrame.

Main Functions:
---------------
- extract_contours(...): Convert binary mask to valid polygon geometries.
- generate_isochrones(...): Orchestrates the full interpolation → polygon generation → post-processing pipeline.
"""


import logging
import time
from typing import Dict, List, Optional, Union, Tuple

import cv2
import numpy as np
import geopandas as gpd
from pyproj import Transformer, CRS
from affine import Affine
from shapely.geometry import (
    Point, Polygon, LineString, MultiPolygon
)
from shapely.ops import polygonize
from scipy.ndimage import (
    binary_dilation, binary_closing, binary_fill_holes
)
from skimage import measure

from app.core.config import WATER_DIFF_TIMEOUT, TransportModes
from app.core.data_types import TravelData
from app.processing.isochrones.interpolation import (
    inverse_distance_weighting, fill_gaps
)
from app.processing.isochrones.utils import (
    extract_travel_times, validate_geometry, 
    post_processing, fast_difference_with_water
)

logger = logging.getLogger(__name__)

def extract_contours(
    level: float,
    mask: np.ndarray,
    city_mask_area: Optional[MultiPolygon],
    transform: Affine, 
    performance: bool,
    water_gdf: Optional[gpd.GeoDataFrame] = None,
    water_sindex: Optional[gpd.sindex.SpatialIndex] = None,
    start_time: Optional[float] = None,
    max_duration: float = 5.0
) -> Tuple[
    List[Dict[str, Union[float, Polygon, MultiPolygon]]], 
    List[Dict[str, Union[float, Polygon, MultiPolygon]]], 
    bool
]:
    """
    Converts a binary raster mask into polygon contours for a given travel time level.
    Applies spatial clipping using either the full city geometry or a simplified water-based subtraction.

    Behavior:
    ---------
    - If `performance=False`: subtract `city_mask_area` normally.
    - If `performance=True`:
        - Attempts fast water subtraction using `fast_difference_with_water`.
        - If the cumulative time budget (`max_duration`) is exceeded, skips clipping.
        - Returns both raw and clipped geometries for fallback control.

    Args:
        level (float): Travel time level associated with the mask.
        mask (np.ndarray): Binary mask for the current level.
        city_mask_area (MultiPolygon): Geometry used for clipping (e.g. city minus water), or None if performance mode.
        transform (Affine): Affine transformation to map pixel to CRS coordinates.
        performance (bool): Whether to skip expensive geometry and raster operations.
        water_gdf (GeoDataFrame, optional): Water polygons for subtraction.
        water_sindex (gpd.sindex.SpatialIndex, optional): Spatial index for water_gdf.
        start_time (float, optional): Time reference for timeout check.
        max_duration (float): Max total allowed time for clipping in seconds.

    Returns:
        Tuple[
            raw_results: Unclipped geometries (used if clipping skipped),
            water_results: Geometries clipped against water (or full city),
            skipped: Boolean flag indicating if clipping was skipped
        ]
    """
    mask = binary_fill_holes(mask)
    mask = binary_closing(mask, structure=np.ones((5, 5)))
    mask = binary_dilation(mask, structure=np.ones((3, 3)))

    contours = measure.find_contours(mask.astype(np.uint8), level=0.5)
    lines = [
        LineString([(c[1], c[0]) for c in contour])
        for contour in contours if len(contour) > 1
    ]
    
    raw_results = []
    water_results = []
    skipped = False

    for poly in polygonize(lines):
        polygon_transformed = Polygon([transform * (x, y) for x, y in poly.exterior.coords])
        geom = validate_geometry(polygon_transformed)
        if geom.is_empty or geom.area < 1e-6:
            continue
        
        if not performance:
            clipped_poly = geom.intersection(city_mask_area)
        else:
            raw_results.append({"level": level, "geometry": geom})
            if time.monotonic() - start_time < max_duration:
                clipped_poly = fast_difference_with_water(geom, water_gdf, water_sindex)
            else:
                clipped_poly = geom
                skipped = True

        if not clipped_poly.is_empty and clipped_poly.area >= 1e-6:
            water_results.append({"level": level, "geometry": clipped_poly})

    return raw_results, water_results, skipped

def generate_isochrones(
    travel_data: TravelData,
    mode: TransportModes,
    city_poly: Polygon,
    initial_crs: CRS,
    target_crs: CRS,
    transformer: Transformer,
    water_gdf: Optional[gpd.GeoDataFrame] = None,
    water_sindex: Optional[gpd.sindex.SpatialIndex] = None,
    smooth_sigma: float = 3,
    center: Optional[Point] = None,
    network_isochrones: bool = False,
    input_station: Optional[str] = None,
    performance: bool = False
) -> gpd.GeoDataFrame:
    """
    Generates isochrones by interpolating travel times, extracting raster contours, 
    and converting them into spatial polygons. Supports both full-network and 
    point-based isochrones.
    
    In performance mode:
    - Grid resolution is lower.
    - No morphological smoothing or hole-filling.
    - Clipping is restricted to water-body subtraction for speed.
    - Falls back to unclipped raw geometries if timeout exceeded in performance mode.

    Args:
        travel_data (TravelData): Dictionary of travel time data per mode.
        mode (TransportModes): Mode of transportation (e.g., "walk", "cycle", etc.).
        city_poly (Polygon): Bounding city polygon in WGS84.
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        transformer (Transformer): Transforms data from initial crs to target crs.
        water_gdf (GeoDataFrame, optional): Water features for fast clipping.
        water_sindex (gpd.sindex.SpatialIndex, optional): Spatial index for water_gdf.
        smooth_sigma (float): Smoothing parameter for Gaussian filter.
        center (Point, optional): Origin point in WGS84 (for point isochrones).
        network_isochrones (bool): Whether this is based on network travel time.
        input_station (str, optional): Station name (for point isochrones).
        performance (bool): If True, uses faster approximations with minor accuracy loss.

    Returns:
        gpd.GeoDataFrame: Polygonized isochrone geometries with travel time levels.
    """
    logger.info(f'Generating isochrones for mode={mode}...')
    
    points, times, center = extract_travel_times(travel_data, mode, center, network_isochrones=network_isochrones)
    if len(points) < 4:
        logger.error("Not enough data points to generate isochrones.")
        raise ValueError("Not enough data points to generate isochrones.")
    
    # --- Coordinate projection ---
    points = np.array([transformer.transform(lon, lat) for lon, lat in points])
    times_max, times_min = times.max(), times.min()
    levels = np.arange(times_min, times_max + 1)
    
    # --- Grid creation ---
    buffer = 1000
    resolution = 250 if performance else (1000 if network_isochrones else 500)
    k = 8
    
    lon_min, lat_min = points.min(axis=0)
    lon_max, lat_max = points.max(axis=0)

    grid_x, grid_y = np.meshgrid(
        np.linspace(lon_min - buffer, lon_max + buffer, resolution),
        np.linspace(lat_min - buffer, lat_max + buffer, resolution)
    )

    grid_extent_x = lon_max - lon_min + 2 * (buffer - 150)
    grid_extent_y = lat_max - lat_min + 2 * (buffer - 150)
    max_radius = min(grid_extent_x, grid_extent_y) / 2
    
    # --- Interpolation ---
    normalized_times = (times - times_min) / (times_max - times_min)
    grid_z = inverse_distance_weighting(points, normalized_times, grid_x, grid_y, power=2, k=k)

    if np.all(np.isnan(grid_z)):
        logger.error("Interpolated grid contains only NaN values.")
        raise ValueError("Interpolated grid contains only NaN values.")
    if not performance:
        grid_z = fill_gaps(grid_z, smooth_sigma)
        grid_z = cv2.GaussianBlur(grid_z.astype(np.float32), (3, 3), 1)
    grid_z = grid_z * (times_max - times_min) + times_min

    # --- Geometry preparation ---
    if performance:
        city_mask_area = None
    else:
        city_projected = gpd.GeoSeries([city_poly], crs=initial_crs).to_crs(target_crs).iloc[0]
        city_mask_area = fast_difference_with_water(city_projected, water_gdf, water_sindex)

    xres = (lon_max + buffer - (lon_min - buffer)) / resolution
    yres = (lat_max + buffer - (lat_min - buffer)) / resolution
    transform = Affine.translation(lon_min - buffer, lat_min - buffer) * Affine.scale(xres, yres)
    
    # --- Contour extraction ---
    raw_isochrones = []
    water_isochrones = []
    epsilon = 0.01
    start_time = time.monotonic()
    mask = grid_z <= levels[0] + epsilon
    raw_results, water_results, skipped = extract_contours(levels[0], mask, city_mask_area,
                                  transform, performance, water_gdf, water_sindex, 
                                  start_time, WATER_DIFF_TIMEOUT)
    if performance:
        raw_isochrones.extend(raw_results)
    water_isochrones.extend(water_results)

    for i in range(len(levels) - 1):
        mask = (grid_z > levels[i]) & (grid_z <= levels[i + 1] + epsilon)
        raw_results, water_results, skipped = extract_contours(levels[i + 1], mask, city_mask_area, 
                                      transform, performance, water_gdf, water_sindex,
                                      start_time, WATER_DIFF_TIMEOUT)
        if performance:
            raw_isochrones.extend(raw_results)
        water_isochrones.extend(water_results)
    
    if performance and skipped:
        logger.warning("Falling back to raw isochrones (water clipping incomplete due to timeout).")
        isochrones = raw_isochrones
    else:
        isochrones = water_isochrones
        
    isochrones = [item for item in isochrones if item is not None]
    if not isochrones:
        logger.error("No isochrones generated. Check input travel data and interpolation.")
        raise ValueError("No isochrones generated. Check input travel data and interpolation.")

    isochrones_gdf = gpd.GeoDataFrame(isochrones, columns=["level", "geometry"], crs=target_crs)
    isochrones_gdf = post_processing(
        isochrones_gdf, max_radius, initial_crs, 
        target_crs, center, network_isochrones=network_isochrones
    )

    isochrones_gdf.attrs = {
        "type": "network" if network_isochrones else "point",
        "mode": mode,
        "center": [center.x, center.y] if center else None,
        "name": input_station or "null"
    }
    
    logger.info(f'Successfully created isochrones for mode={mode}')

    return isochrones_gdf