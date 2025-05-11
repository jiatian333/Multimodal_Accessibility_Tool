"""
Radial Sampling Grid Generator

This module generates a radial sampling grid of points around a specified center point
while avoiding water bodies and enforcing boundary constraints.

Functions
---------
- generate_radial_grid(...): Generates a radial distribution of sampling points, 
                             adapted to transport mode and performance needs.

Returns
-------
- List[Point]: Projected radial points in EPSG:4326.
"""


from typing import List, Optional

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from sklearn.cluster import KMeans

from app.core.config import SEED, TransportModes

def generate_radial_grid(
    center_point: Point,
    polygon: Polygon,
    water_gdf: gpd.GeoDataFrame,
    water_sindex: gpd.sindex.SpatialIndex,
    max_radius: float,
    mode: TransportModes,
    performance: bool,
    transformer: Transformer,
    num_rings: Optional[int] = None,
    base_points: Optional[int] = None,
    offset_range: Optional[int] = None,
    max_points: Optional[int] = None
) -> List[Point]:
    """
    Generate a radial grid of sample points around a center point.

    Points are spaced in concentric rings and filtered to avoid water bodies
    and remain inside a bounding polygon (except for performance mode). 
    Optional clustering limits the total number of points based on performance settings.

    Args:
        center_point (Point): Center of the radial grid (EPSG:4326).
        polygon (Polygon): Study area boundary.
        water_gdf (GeoDataFrame): Water bodies (projected).
        water_sindex (gpd.sindex.SpatialIndex): R-tree index of the water_gdf for fast spatial queries.
        max_radius (float): Maximum radius for sampling in meters.
        mode (TransportModes): Transport mode for grid density adjustments.
        performance (bool): Use faster/leaner configuration.
        transformer (Transformer): Transforms data from initial crs to target crs.
        num_rings (Optional[int]): Override number of concentric rings.
        base_points (Optional[int]): Base number of points per ring.
        offset_range (Optional[int]): Maximum random offset applied to each point in meters.
        max_points (Optional[int]): Limit total number of returned points.

    Returns:
        List[Point]: Radial points (EPSG:4326), including center.
    """
    np.random.seed(SEED)

    # --- Mode-dependent defaults ---
    if mode == 'walk':
        num_rings = num_rings or (5 if performance else 6)
        base_points = base_points or 8
        offset_range = offset_range or 50
        max_points = max_points or (50 if performance else 99)
    elif mode in ['cycle', 'bicycle_rental', 'escooter_rental']:
        num_rings = num_rings or (6 if performance else 10)
        base_points = base_points or 7
        offset_range = offset_range or 100
        max_points = max_points or (50 if performance else 199)
    else:
        num_rings = num_rings or (7 if performance else 12)
        base_points = base_points or 6
        offset_range = offset_range or 150
        max_points = max_points or (50 if performance else 249)
    
    if not performance:
        poly_coords = np.array(polygon.exterior.coords)
        poly_x, poly_y = transformer.transform(poly_coords[:, 0], poly_coords[:, 1])
        polygon_proj = Polygon(zip(poly_x, poly_y))

    center_x, center_y = transformer.transform(center_point.x, center_point.y)
    center_proj = Point(center_x, center_y)
    
    def is_valid(pt: Point) -> bool:
        """
        Validates whether a point can be sampled:
        
        - Must not intersect with water bodies (always enforced).
        - Must lie within the polygon boundary (only when performance=False).

        Args:
            pt (Point): The candidate point to validate (projected CRS).

        Returns:
            bool: True if the point satisfies spatial constraints.
        """
        hits = list(water_sindex.intersection(pt.bounds))
        water_ok = not hits or not water_gdf.iloc[hits].intersects(pt).any()
        return water_ok if performance else polygon_proj.contains(pt) and water_ok

    selected_points: List[Point] = []

    # --- Add close directional points ---
    angle_offsets = np.array([np.pi/4, 3*np.pi/4, 5*np.pi/4, 7*np.pi/4])
    small_radius = max_radius / 10
    extra_offsets = np.column_stack(
        (small_radius * np.cos(angle_offsets), small_radius * np.sin(angle_offsets))
    )

    for dx, dy in extra_offsets:
        pt = Point(center_proj.x + dx, center_proj.y + dy)
        if is_valid(pt):
            lon, lat = transformer.transform(pt.x, pt.y, direction='INVERSE')
            selected_points.append(Point(lon, lat))

    # --- Full radial pattern ---
    for i in range(1, num_rings + 1):
        radius = (i / num_rings) * max_radius
        n_points = base_points * (1 + i // 2)
        base_angles = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
        random_shift = np.random.uniform(-np.pi/5, np.pi/5)
        angles = (base_angles + random_shift) % (2 * np.pi)
        offsets = np.column_stack((radius * np.cos(angles), radius * np.sin(angles)))
        offsets += np.random.uniform(-offset_range, offset_range, offsets.shape)

        for dx, dy in offsets:
            pt = Point(center_proj.x + dx, center_proj.y + dy)
            if is_valid(pt):
                lon, lat = transformer.transform(pt.x, pt.y, direction='INVERSE')
                selected_points.append(Point(lon, lat))

    # --- Optional: clustering to reduce excessive points ---
    if len(selected_points) > max_points:
        arr = np.array([(pt.x, pt.y) for pt in selected_points])
        kmeans = KMeans(n_clusters=max_points, random_state=SEED, n_init=10).fit(arr)
        selected_points = [Point(x, y) for x, y in kmeans.cluster_centers_]
    
    if not performance:
        selected_points.append(center_point)
    
    return selected_points