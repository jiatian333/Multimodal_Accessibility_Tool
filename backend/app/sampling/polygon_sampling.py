"""
Isochrone Sampling Coverage Tools

This module provides functions to:
- Identify geographic regions not yet covered by isochrones.
- Detect large isochrone geometries for targeted sampling.

Functions
---------
- extract_unsampled_area(...): Finds uncovered regions by subtracting existing isochrones and water.
- identify_large_isochrones(...): Filters out large isochrones using relative area thresholds.

Returns
-------
- Uncovered regions as MultiPolygons
- Large isochrone geometries as Polygon or MultiPolygon objects
"""


from typing import List, Union, Optional

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from pyproj import CRS

def extract_unsampled_area(
    area_polygon: Polygon,
    water_combined: GeometryCollection,
    isochrones_gdf: gpd.GeoDataFrame
) -> MultiPolygon:
    """
    Identifies areas in the polygon that remain unsampled by subtracting isochrone and water coverage.

    Args:
        area_polygon (Polygon): Full area boundary.
        water_combined (GeometryCollection): Combined water features (e.g., rivers, lakes).
        isochrones_gdf (GeoDataFrame): Existing isochrone coverage.

    Returns:
        MultiPolygon: Uncovered land area that could benefit from additional sampling.
    """
    union_iso = isochrones_gdf.geometry.union_all()
    uncovered_area = area_polygon.difference(unary_union([water_combined, union_iso]))
    return uncovered_area


def identify_large_isochrones(
    isochrones_gdf: gpd.GeoDataFrame,
    target_crs: CRS, 
    initial_crs: CRS, 
    area_threshold: float = 0.05
) -> List[Optional[Union[Polygon, MultiPolygon]]]:
    """
    Extracts large isochrone geometries exceeding a relative area threshold.

    Args:
        isochrones_gdf (GeoDataFrame): Isochrone shapes in EPSG:4326.
        target_crs (CRS): CRS of target data for accurate distance calculation (EPSG:2056).
        initial_crs (CRS): CRS of initial data (EPSG:4326).
        area_threshold (float): Minimum relative area threshold (e.g., 0.05 = 5%).

    Returns:
        List[Optional[Union[Polygon, MultiPolygon]]]: Large isochrone geometries in EPSG:4326.
    """
    projected = isochrones_gdf.to_crs(target_crs)
    total_area = projected.geometry.area.sum()
    large_isochrones = projected[projected.geometry.area / total_area > area_threshold]
    return large_isochrones.to_crs(initial_crs).geometry.tolist()