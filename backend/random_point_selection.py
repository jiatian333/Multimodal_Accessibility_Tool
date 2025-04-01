from variables import *
from calculate_intersections import save_and_load_intersections

import numpy as np
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import Point
from scipy.spatial import KDTree

def generate_adaptive_sample_points(polygon, water_combined, target_crs, mode=MODE):
    np.random.seed(SEED)
    polygon = gpd.GeoSeries(polygon, crs="EPSG:4326").to_crs(target_crs).iloc[0]
    water_combined = gpd.GeoSeries(water_combined, crs="EPSG:4326").to_crs(target_crs).iloc[0]

    network_type = {
        'cycle': 'bike', 'bicycle_rental': 'bike', 'escooter_rental': 'bike',
        'self-drive-car': 'drive', 'car_sharing': 'drive'
    }.get(mode, 'walk')

    if EXTRA_POINTS > 0:
        intersection_dict = save_and_load_intersections(
            network_type, target_crs, polygon, water_combined, BASE_GRID_SIZE, DENSITY
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
    point_geoms = gpd.GeoSeries([Point(p) for p in points])

    valid_mask = polygon.contains(point_geoms) & ~water_combined.intersects(point_geoms)
    valid_points = points[valid_mask]
    
    if EXTRA_POINTS > 0 and intersection_counts.sum() > 0:
        valid_indices = np.where(intersection_counts > 0)[0]
        valid_weights = np.log(intersection_counts[valid_indices])
        valid_weights /= valid_weights.sum()

        extra_indices = np.random.choice(valid_indices, EXTRA_POINTS, p=valid_weights)
        extra_offsets = np.random.uniform(-BASE_GRID_SIZE / 2, BASE_GRID_SIZE / 2, (EXTRA_POINTS, 2))
        extra_points = np.column_stack((x_vals[extra_indices], y_vals[extra_indices])) + BASE_GRID_SIZE / 2 + extra_offsets

        extra_geoms = gpd.GeoSeries([Point(p) for p in extra_points])
        valid_extra_mask = polygon.contains(extra_geoms) & ~water_combined.intersects(extra_geoms)
        valid_extra_points = extra_points[valid_extra_mask]
        valid_points = np.vstack((valid_points, valid_extra_points))
    
    tree = KDTree(valid_points)
    pairs = tree.query_pairs(r=100)
    clusters = {idx: set([idx]) for idx in range(len(valid_points))}

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
    return gdf_points.to_crs(epsg=4326).geometry.tolist()

def extract_unsampled_area(area_polygon, water_combined, isochrones_gdf):
    """
    Returns the geometry (or MultiPolygon) of the unsampled area:
    The difference between the overall city polygon and the union of the isochrone polygons.
    """
    union_iso = isochrones_gdf.geometry.union_all()
    unsampled_area = area_polygon.difference(unary_union([water_combined, union_iso]))
    return area_polygon.difference(union_iso)

def identify_large_isochrones(isochrones_gdf, area_threshold=0.05, crs_epsg=2056):
    """
    Identify large isochrones based on their area relative to the total covered area.
    Converts to a projected CRS for accurate area calculations.
    Returns a list of large isochrone geometries.
    """
    projected_gdf = isochrones_gdf.to_crs(epsg=crs_epsg)
    total_area = projected_gdf.geometry.area.sum()
    large_isochrones = projected_gdf[projected_gdf.geometry.area / total_area > area_threshold]
    return large_isochrones.to_crs(epsg=4326).geometry.tolist()

def random_points_in_polygon(polygon, num_points):
    """
    Returns a list of random Shapely Point objects inside the given polygon.
    Uses rejection sampling with batch processing for efficiency.
    """
    
    np.random.seed(SEED)
    minx, miny, maxx, maxy = polygon.bounds
    points = []
    while len(points) < num_points:
        random_x = np.random.uniform(minx, maxx, num_points - len(points))
        random_y = np.random.uniform(miny, maxy, num_points - len(points))
        candidates = [Point(x, y) for x, y in zip(random_x, random_y)]
        points.extend([p for p in candidates if polygon.contains(p)])
    return points

def sample_additional_points(isochrones_gdf, city_polygon, water_combined, n_unsampled=50, n_large_isochrones=50):
    """
    Identify unsampled areas within the city and large uniform isochrones, then sample additional points.
    Returns a list of Shapely Points (in WGS84) that can be merged with the existing adaptive sample points.
    """
    
    additional_points = []
    unsampled_area = extract_unsampled_area(city_polygon, water_combined, isochrones_gdf)
    if unsampled_area.is_empty:
        return additional_points
    
    areas_to_sample = list(unsampled_area.geoms) if unsampled_area.geom_type == 'MultiPolygon' else [unsampled_area]
    total_area = sum(area.area for area in areas_to_sample)
    for area in areas_to_sample:
        additional_points.extend(random_points_in_polygon(area, int(n_unsampled * (area.area / total_area))))
    
    large_isochrones = identify_large_isochrones(isochrones_gdf)
    if large_isochrones:
        total_iso_area = sum(iso.area for iso in large_isochrones)
        for iso in large_isochrones:
            additional_points.extend(random_points_in_polygon(iso, int(n_large_isochrones * (iso.area / total_iso_area))))
    
    return additional_points

def generate_radial_grid(center_point, polygon, water_mask, max_radius, target_crs, num_rings=3, base_points=6, offset_range=5):
    """
    Generates a radial grid and removes points falling in water bodies.

    Parameters:
    - center_point (shapely.geometry.Point): Input point in WGS 84 (lat/lon).
    - network_area (str): Place name for fetching water data.
    - max_radius (float): Maximum radius (meters).
    - num_rings (int): Number of rings.
    - base_points (int): Base points per ring.
    - target_crs (str): Projected CRS for accurate distance calculations.

    Returns:
    - List of (lat, lon) tuples (excluding water-covered points).
    """
    
    np.random.seed(SEED)
    water_mask = gpd.GeoSeries(water_mask, crs="EPSG:4326").to_crs(target_crs).iloc[0]
    polygon = gpd.GeoSeries(polygon, crs="EPSG:4326").to_crs(target_crs).iloc[0]
    center_projected = gpd.GeoSeries([center_point], crs="EPSG:4326").to_crs(target_crs).geometry.iloc[0]
    selected_points = []
    
    additional_points_radius = max_radius / 10
    angles = np.random.uniform(0, 2 * np.pi, 4)
    offsets = np.column_stack((additional_points_radius * np.cos(angles), additional_points_radius * np.sin(angles)))
    
    for delta_x, delta_y in offsets:
        new_point = Point(center_projected.x + delta_x, center_projected.y + delta_y)
        if polygon.contains(new_point) and not water_mask.contains(new_point):
            selected_points.append(gpd.GeoSeries([new_point], crs=target_crs).to_crs("EPSG:4326").geometry.iloc[0])
    
    for i in range(1, num_rings + 1):
        radius = (i / num_rings) * max_radius
        num_points = base_points * (1 + i // 2)
        angles = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
        offsets = np.column_stack((radius * np.cos(angles), radius * np.sin(angles)))
        offsets += np.random.uniform(-offset_range, offset_range, offsets.shape)
        
        for delta_x, delta_y in offsets:
            new_point = Point(center_projected.x + delta_x, center_projected.y + delta_y)
            if polygon.contains(new_point) and not water_mask.contains(new_point):
                selected_points.append(gpd.GeoSeries([new_point], crs=target_crs).to_crs("EPSG:4326").geometry.iloc[0])
    
    return selected_points