from variables import *
from calculate_intersections import save_and_load_intersections

import osmnx as ox
import numpy as np
import geopandas as gpd
import pyproj
from shapely.geometry import Point
from scipy.spatial import KDTree

def generate_adaptive_sample_points(polygon, mode=MODE):
    np.random.seed(SEED)

    # **Step 1: Get the area polygon in the correct CRS**
    target_crs = pyproj.CRS.from_epsg(2056)
    polygon = polygon.to_crs(target_crs).geometry.union_all()

    # **Step 2: Exclude water bodies**
    water_gdf = ox.features_from_place(NETWORK_AREA, tags={"natural": "water"}).to_crs(target_crs).geometry.union_all()
    river_gdf = ox.features_from_place(NETWORK_AREA, tags={"waterway": True}).to_crs(target_crs).geometry.union_all()

    # **Step 3: Determine transport network type**
    network_type = {
        'cycle': 'bike', 'bicycle_rental': 'bike', 'escooter_rental': 'bike',
        'self-drive-car': 'drive', 'car_sharing': 'drive'
    }.get(mode, 'walk')

    # **Step 4: Load intersection densities**
    if EXTRA_POINTS > 0:
        intersection_dict = save_and_load_intersections(network_type, target_crs, polygon, water_gdf, river_gdf, grid_size=BASE_GRID_SIZE, filename=DENSITY_DATA_PATH)
        intersection_counts = intersection_dict[network_type][BASE_GRID_SIZE]

    # **Step 5: Define the grid exactly as in intersection calculation**
    minx, miny, maxx, maxy = polygon.bounds
    x_vals = np.linspace(minx, maxx, int(np.ceil((maxx - minx) / BASE_GRID_SIZE)))
    y_vals = np.linspace(miny, maxy, int(np.ceil((maxy - miny) / BASE_GRID_SIZE)))

    # **Exclude grids with zero intersections**
    if EXTRA_POINTS > 0:
        valid_indices = [i for i, count in enumerate(intersection_counts) if count > 0]
        valid_intersections = [intersection_counts[i] for i in valid_indices]
        log_intersection_counts = np.log(np.array(valid_intersections, dtype=float))

        # Normalize the log-transformed weights
        total_weight = np.sum(log_intersection_counts)
        if total_weight > 0:
            valid_weights = log_intersection_counts / total_weight  # Normalize to probabilities
        else:
            valid_weights = np.ones(len(valid_intersections))  # If no valid weights, fallback to uniform distribution

    # **Step 6: Generate initial base grid**
    points = []
    for x in x_vals:
        for y in y_vals:
            random_offset = np.random.uniform(-BASE_GRID_SIZE / 3, BASE_GRID_SIZE / 3, size=2)
            p = Point(x + BASE_GRID_SIZE / 2 + random_offset[0], y + BASE_GRID_SIZE / 2 + random_offset[1])
            if polygon.intersects(p) and not water_gdf.intersects(p) and not river_gdf.intersects(p):
                points.append(p)

    # **Step 7: Generate extra adaptive points**
    if EXTRA_POINTS > 0:
        for _ in range(EXTRA_POINTS):
            # Randomly sample a grid index based on the weights
            grid_idx = np.random.choice(valid_indices, p=valid_weights)
            grid_x = x_vals[grid_idx % len(x_vals)]
            grid_y = y_vals[grid_idx // len(x_vals)]

            # **Ensure that the grid has at least one intersection before proceeding**
            if intersection_counts[grid_idx] > 0:

                random_offset = np.random.uniform(-BASE_GRID_SIZE / 2, BASE_GRID_SIZE / 2, size=2)
                new_point = Point(grid_x + BASE_GRID_SIZE / 2 + random_offset[0], grid_y + BASE_GRID_SIZE / 2 + random_offset[1])

                if polygon.intersects(new_point) and not water_gdf.intersects(new_point) and not river_gdf.intersects(new_point):
                    points.append(new_point)

    # **Step 8: Filter points using KDTree for redundancy reduction**
    coords = np.array([[p.x, p.y] for p in points])
    tree = KDTree(coords)

    # Find pairs of points within the specified radius (half of the grid size)
    pairs = tree.query_pairs(r=100)

    # Create a set to track which points should be kept
    keep_points = set(range(len(points)))

    # To store clusters of points that are too close together
    clusters = {}

    # Group points that are within the radius of each other
    for idx1, idx2 in pairs:
        if idx1 not in clusters:
            clusters[idx1] = set([idx1, idx2])
        else:
            clusters[idx1].add(idx2)

        if idx2 not in clusters:
            clusters[idx2] = set([idx2, idx1])
        else:
            clusters[idx2].add(idx1)

    # For each cluster (group of points that are too close together), keep only one point
    for cluster in clusters.values():
        if len(cluster) > 1:
            # Randomly choose one point to keep from the cluster
            keep_points -= cluster
            keep_points.add(np.random.choice(list(cluster)))

    # Filter the points based on the `keep_points` set
    final_points = [points[i] for i in keep_points]

    # **Step 9: Convert to GeoDataFrame & return**
    gdf_points = gpd.GeoDataFrame(geometry=final_points, crs=target_crs)
    gdf_points_wgs84 = gdf_points.to_crs(epsg=4326)

    return gdf_points_wgs84.geometry.tolist()

def extract_unsampled_area(area_polygon, isochrones_gdf):
    """
    Returns the geometry (or MultiPolygon) of the unsampled area:
    The difference between the overall city polygon and the union of the isochrone polygons.
    """
    union_iso = isochrones_gdf.union_all()
    unsampled_area = area_polygon.difference(union_iso)
    return unsampled_area

def identify_large_isochrones(isochrones_gdf, area_threshold=0.05, crs_epsg=2056):
    """
    Identify large isochrones based on their area relative to the total covered area.
    Converts to a projected CRS for accurate area calculations.
    Returns a list of large isochrone geometries.
    """
    projected_gdf = isochrones_gdf.to_crs(epsg=crs_epsg)  # Convert to projected CRS
    total_area = projected_gdf.geometry.area.sum()  # Compute total isochrone area

    # Select isochrones that are larger than the threshold proportion of the total area
    large_isochrones = projected_gdf[projected_gdf.geometry.area / total_area > area_threshold]

    return large_isochrones.to_crs(epsg=4326).geometry.tolist() 

def random_points_in_polygon(polygon, num_points):
    """
    Returns a list of random Shapely Point objects inside the given polygon.
    Uses rejection sampling based on the polygon's bounding box.
    """
    np.random.seed(SEED)
    pts = []
    minx, miny, maxx, maxy = polygon.bounds
    while len(pts) < num_points:
        p = Point(np.random.uniform(minx, maxx), np.random.uniform(miny, maxy))
        if polygon.contains(p):
            pts.append(p)
    return pts

def sample_additional_points(isochrones_gdf, city_polygon, n_unsampled=50, n_large_isochrones=50):
    """
    Identify unsampled areas within the city and large uniform isochrones, then sample additional points.
    Returns a list of Shapely Points (in WGS84) that can be merged with the existing adaptive sample points.
    """
    additional_points = []

    # Sample points from completely unsampled areas
    unsampled_area = extract_unsampled_area(city_polygon, isochrones_gdf)
    
    if isinstance(unsampled_area, gpd.GeoSeries):  # Handle GeoSeries case
        unsampled_area = unsampled_area.union_all()
    
    if not unsampled_area.is_empty:
        if unsampled_area.geom_type == 'Polygon':
            areas_to_sample = [unsampled_area]
        elif unsampled_area.geom_type == 'MultiPolygon':
            areas_to_sample = list(unsampled_area.geoms)
        else:
            areas_to_sample = []
        
        total_area = sum(area.area for area in areas_to_sample)
        for area in areas_to_sample:
            area_points = int(n_unsampled * (area.area / total_area))
            additional_points.extend(random_points_in_polygon(area, area_points))

    # Sample points within large uniform isochrones
    large_isochrones = identify_large_isochrones(isochrones_gdf)
    if large_isochrones:
        total_iso_area = sum(iso.area for iso in large_isochrones)
        for iso in large_isochrones:
            iso_points = int(n_large_isochrones * (iso.area / total_iso_area))
            additional_points.extend(random_points_in_polygon(iso, iso_points))

    return additional_points

def generate_radial_grid(center_point, polygon, max_radius, network_area=NETWORK_AREA, num_rings=3, base_points=6, offset_range=5):
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

    # Load water bodies and rivers
    target_crs = pyproj.CRS.from_epsg(2056)
    polygon = polygon.to_crs(target_crs).geometry.union_all()
    water_gdf = ox.features_from_place(network_area, tags={"natural": "water"}).to_crs(target_crs).geometry.union_all()
    river_gdf = ox.features_from_place(network_area, tags={"waterway": True}).to_crs(target_crs).geometry.union_all()
    water_mask = water_gdf.union(river_gdf)  # Combine water geometries

    # Convert center point to projected CRS
    center_gdf = gpd.GeoDataFrame(geometry=[center_point], crs="EPSG:4326").to_crs(target_crs)
    center_projected = center_gdf.geometry.iloc[0]  # Now in meters

    selected_points = []

    # Add additional points closer to the center
    # Add 4 additional points within a small radius near the center
    additional_points_radius = max_radius / 10  # small distance for points around the center
    for _ in range(4):  # Generate 4 additional points
        angle = np.random.uniform(0, 2 * np.pi)
        delta_x = additional_points_radius * np.cos(angle)
        delta_y = additional_points_radius * np.sin(angle)

        new_point_projected = Point(center_projected.x + delta_x, center_projected.y + delta_y)

        # Convert back to lat/lon
        new_point_gdf = gpd.GeoDataFrame(geometry=[new_point_projected], crs=target_crs).to_crs("EPSG:4326")

        # Check if the point is in water
        if polygon.intersects(new_point_projected) and not water_mask.intersects(new_point_projected):
            selected_points.append(new_point_gdf.geometry.iloc[0])

    # Continue with the existing logic for rings
    for i in range(1, num_rings + 1):
        radius = (i / num_rings) * max_radius  # Adjust spacing
        num_points = base_points * (1 + i // 2)  # Increase points gradually
        angles = np.linspace(0, 2 * np.pi, num_points, endpoint=False)

        for theta in angles:
            delta_x = radius * np.cos(theta)  # X offset in meters
            delta_y = radius * np.sin(theta)  # Y offset in meters
            
            # Add a random offset within the specified range
            delta_x += np.random.uniform(-offset_range, offset_range)
            delta_y += np.random.uniform(-offset_range, offset_range)
            
            new_point_projected = Point(center_projected.x + delta_x, center_projected.y + delta_y)

            # Convert back to lat/lon
            new_point_gdf = gpd.GeoDataFrame(geometry=[new_point_projected], crs=target_crs).to_crs("EPSG:4326")

            # Check if the point is in water
            if polygon.intersects(new_point_projected) and not water_mask.intersects(new_point_projected):
                selected_points.append(new_point_gdf.geometry.iloc[0])

    return selected_points