"""
Isochrone Generation and Contour Extraction

This module provides the full pipeline for generating isochrones from spatial travel time data.
It supports both network-wide and point-centered isochrones and handles raster interpolation,
geometry extraction, and projection management.

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
from typing import Dict, List, Optional, Union

import cv2
import numpy as np
import geopandas as gpd
from pyproj import Transformer, CRS
from affine import Affine
from shapely.geometry import (
    Point, Polygon, LineString, GeometryCollection, MultiPolygon
)
from shapely.ops import polygonize
from scipy.ndimage import (
    binary_dilation, binary_closing, binary_fill_holes
)
from skimage import measure

from app.core.config import TransportModes
from app.core.data_types import TravelData
from app.processing.isochrones.interpolation import (
    inverse_distance_weighting, fill_gaps
)
from app.processing.isochrones.utils import (
    extract_travel_times, validate_geometry, post_processing
)

logger = logging.getLogger(__name__)

def extract_contours(
    level: float,
    mask: np.ndarray,
    city_mask_area: MultiPolygon,
    isochrones: List[Dict[str, Union[float, Polygon, MultiPolygon]]],
    transform: Affine
) -> List[Dict[str, Union[float, Polygon, MultiPolygon]]]:
    """
    Converts a binary mask into polygon contours, applies spatial clipping,
    and appends valid shapes to the isochrone list.

    Args:
        level (float): Travel time level associated with the mask.
        mask (np.ndarray): Binary mask for the current level.
        city_mask_area (MultiPolygon): Area within which isochrones must lie (e.g., city minus water).
        isochrones (List[Dict]): Accumulator list of extracted isochrones.
        transform (Affine): Affine transformation to map pixel to CRS coordinates.

    Returns:
        List[Dict[str, Union[float, Polygon, MultiPolygon]]]: Updated list of polygonized isochrones for the level.
    """
    mask = binary_fill_holes(mask)
    mask = binary_closing(mask, structure=np.ones((5, 5)))
    mask = binary_dilation(mask, structure=np.ones((3, 3)))

    contours = measure.find_contours(mask.astype(np.uint8), level=0.5)
    lines = [
        LineString([(c[1], c[0]) for c in contour]) 
        for contour in contours if len(contour) > 1
    ]

    for poly in polygonize(lines):
        polygon_transformed = Polygon([transform * (x, y) for x, y in poly.exterior.coords])
        clipped_poly = validate_geometry(polygon_transformed).intersection(city_mask_area)

        if not clipped_poly.is_empty and clipped_poly.area >= 1e-6:
            isochrones.append({"level": level, "geometry": clipped_poly})

    return isochrones


def generate_isochrones(
    travel_data: TravelData,
    mode: TransportModes,
    water_combined: GeometryCollection,
    city_poly: Polygon,
    initial_crs: CRS,
    target_crs: CRS,
    transformer: Transformer,
    smooth_sigma: float = 3,
    center: Optional[Point] = None,
    network_isochrones: bool = False,
    input_station: Optional[str] = None
) -> gpd.GeoDataFrame:
    """
    Generates spatial isochrones for a given mode using interpolation and contour extraction.

    Args:
        travel_data (TravelData): Dictionary of travel time data per mode.
        mode (TransportModes): Mode of transportation (e.g., "walk", "cycle", etc.).
        water_combined (GeometryCollection): Water geometry to exclude from city area in WGS84.
        city_poly (Polygon): Bounding city polygon in WGS84.
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        transformer (Transformer): Transforms data from initial crs to target crs.
        smooth_sigma (float): Smoothing parameter for Gaussian filter.
        center (Point, optional): Origin point in WGS84 (for point isochrones).
        network_isochrones (bool): Whether this is based on network travel time.
        input_station (str, optional): Station name (for point isochrones).

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
    buffer = 500
    resolution = 1000 if network_isochrones else 500
    lon_min, lat_min = points.min(axis=0)
    lon_max, lat_max = points.max(axis=0)

    grid_x, grid_y = np.meshgrid(
        np.linspace(lon_min - buffer, lon_max + buffer, resolution),
        np.linspace(lat_min - buffer, lat_max + buffer, resolution)
    )

    grid_extent_x = lon_max - lon_min + 2 * (buffer - 250)
    grid_extent_y = lat_max - lat_min + 2 * (buffer - 250)
    max_radius = min(grid_extent_x, grid_extent_y) / 2
    
    # --- Interpolation ---
    normalized_times = (times - times_min) / (times_max - times_min)
    grid_z = inverse_distance_weighting(points, normalized_times, grid_x, grid_y, power=2, k=8)

    if np.all(np.isnan(grid_z)):
        logger.error("Interpolated grid contains only NaN values.")
        raise ValueError("Interpolated grid contains only NaN values.")

    grid_z = fill_gaps(grid_z, smooth_sigma)
    grid_z = cv2.GaussianBlur(grid_z.astype(np.float32), (3, 3), 1)
    grid_z = grid_z * (times_max - times_min) + times_min

    # --- Geometry preparation ---
    city_projected = gpd.GeoSeries([city_poly], crs=initial_crs).to_crs(target_crs).iloc[0]
    water_projected = gpd.GeoSeries([water_combined], crs=initial_crs).to_crs(target_crs).iloc[0]
    city_mask_area = city_projected.difference(water_projected)

    xres = (lon_max + buffer - (lon_min - buffer)) / resolution
    yres = (lat_max + buffer - (lat_min - buffer)) / resolution
    transform = Affine.translation(lon_min - buffer, lat_min - buffer) * Affine.scale(xres, yres)
    
    # --- Contour extraction ---
    isochrones = []
    epsilon = 0.01
    mask = grid_z <= levels[0] + epsilon
    isochrones = extract_contours(levels[0], mask, city_mask_area, isochrones, transform)

    for i in range(len(levels) - 1):
        mask = (grid_z > levels[i]) & (grid_z <= levels[i + 1] + epsilon)
        isochrones = extract_contours(levels[i + 1], mask, city_mask_area, isochrones, transform)

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