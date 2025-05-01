"""
Utility Functions for GeoDataFrame Processing and Travel Time Extraction

This module contains utility functions to:
- Validate and repair invalid geometries.
- Post-process and dissolve isochrones with optional clipping by a circular boundary.
- Extract known points and travel times from multimodal datasets for interpolation.

Key Functions:
--------------
- validate_geometry(...): Ensures geometry is valid using buffer and make_valid fallback.
- post_processing(...): Cleans, dissolves, clips, and reprojects isochrone geometries.
- extract_travel_times(...): Extracts travel point/time pairs for a given mode and computation type.
"""


import logging
from typing import Tuple, Optional

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

from app.core.config import TransportModes
from app.core.data_types import TravelData

logger = logging.getLogger(__name__)

def validate_geometry(geom: BaseGeometry) -> BaseGeometry:
    """
    Ensures that a given geometry is valid.

    Uses the buffer(0) trick first, then falls back to shapely.make_valid.

    Args:
        geom (BaseGeometry): Input geometry.

    Returns:
        BaseGeometry: Valid geometry (or original if already valid).
    """
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom if geom.is_valid else make_valid(geom)


def post_processing(
    isochrones_gdf: gpd.GeoDataFrame,
    max_radius: float,
    initial_crs: CRS,
    target_crs: CRS, 
    center: Optional[Point],
    network_isochrones: bool
) -> gpd.GeoDataFrame:
    """
    Cleans and prepares raw isochrones by:
    - Removing overlaps (via ordered difference).
    - Optionally clipping to a circular center-based boundary.
    - Reprojecting to the WGS84 CRS for consistent output.

    Args:
        isochrones_gdf (GeoDataFrame): Raw isochrone geometries with travel time levels.
        max_radius (float): Maximum clipping radius (in projected CRS).
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        target_crs (CRS): CRS of target data for accurate distance calculation (e.g., EPSG:2056).
        center (Point, optional): Center point for clipping in EPSG:4326 (if point-based).
        network_isochrones (bool): Whether these are network-wide or centered isochrones.

    Returns:
        GeoDataFrame: Cleaned, validated, optionally clipped, and reprojected geometries.
    """
    isochrones_gdf["area"] = isochrones_gdf["geometry"].area
    isochrones_gdf.sort_values("area", inplace=True)

    processed = []
    covered_area = None

    for _, row in isochrones_gdf.iterrows():
        geom = row.geometry.difference(covered_area) if covered_area else row.geometry
        geom = validate_geometry(geom)

        if not geom.is_empty:
            processed.append({"level": row.level, "geometry": geom})
            covered_area = geom if covered_area is None else covered_area.union(geom)

    cleaned_gdf = gpd.GeoDataFrame(processed, columns=["level", "geometry"], crs=isochrones_gdf.crs)
    cleaned_gdf = cleaned_gdf.dissolve(by="level").reset_index()
    cleaned_gdf["geometry"] = cleaned_gdf["geometry"].apply(validate_geometry)

    if not network_isochrones and center:
        center_point = gpd.GeoSeries([center], crs=initial_crs).to_crs(target_crs).iloc[0]
        circular_mask = center_point.buffer(max_radius)

        cleaned_gdf["geometry"] = cleaned_gdf["geometry"].intersection(circular_mask)
        cleaned_gdf["geometry"] = cleaned_gdf["geometry"].apply(validate_geometry)

    cleaned_gdf = cleaned_gdf.to_crs(initial_crs)
    cleaned_gdf["geometry"] = cleaned_gdf["geometry"].apply(validate_geometry)
    
    return cleaned_gdf

def extract_travel_times(
    travel_data: TravelData,
    mode: TransportModes,
    center: Optional[Point],
    network_isochrones: bool
) -> Tuple[np.ndarray, np.ndarray, Optional[Point]]:
    """
    Extracts travel-time pairs for a given transport mode and computation type.

    Args:
        travel_data (TravelData): Nested structure of precomputed travel times.
        mode (TransportModes): Transport mode key.
        center (Optional[Point]): Central point (for point-based isochrones).
        network_isochrones (bool): True if full-network isochrones are requested.

    Returns:
        Tuple[np.ndarray, np.ndarray, Optional[Point]]: 
            - Numpy array of coordinates [(lon, lat), ...]
            - Corresponding array of travel times [min]
            - Original center point (if applicable)
    """
    if mode not in travel_data:
        logger.error(f"Travel data for mode '{mode}' is missing.")
        raise ValueError(f"Travel data for mode '{mode}' is missing.")
    
    if network_isochrones:
        points, times = zip(*[
            (origin.coords[0], data['travel_time'])
            for origin, data in travel_data[mode].get('isochrones', {}).items()
            if isinstance(origin, Point)
        ])
        return np.array(points), np.array(times), None

    if center not in travel_data[mode].get('point_isochrones', {}):
        logger.error(f"Center {center} not found in travel data for mode '{mode}'.")
        raise ValueError(f"Center {center} not found in travel data for mode '{mode}'.")

    points_data = travel_data[mode]['point_isochrones'][center]
    points = np.array([(p.x, p.y) for p in points_data['points']])
    travel_times = np.array(points_data['travel_times'])

    return points, travel_times, center