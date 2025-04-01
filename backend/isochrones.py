from variables import *
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon
from scipy.spatial import cKDTree
from scipy.ndimage import binary_closing, generic_filter, gaussian_filter
from shapely.ops import unary_union

def prioritize_smallest_isochrones(isochrones_gdf):
    """Ensures smaller isochrones remain on top by subtracting larger ones iteratively."""
    
    projected_gdf = isochrones_gdf.to_crs(epsg=3857)
    projected_gdf["area"] = projected_gdf.geometry.area
    projected_gdf.sort_values(by="area", ascending=True, inplace=True)
    
    processed_isochrones, covered_area = [], None
    
    for _, row in projected_gdf.iterrows():
        polygon = row.geometry.difference(covered_area) if covered_area else row.geometry
        if not polygon.is_empty:
            processed_isochrones.append({"level": row.level, "geometry": polygon})
        covered_area = unary_union([covered_area, row.geometry]) if covered_area else row.geometry
    
    return gpd.GeoDataFrame(processed_isochrones, columns=["level", "geometry"], crs=projected_gdf.crs).to_crs(epsg=4326)

def merge_overlapping_isochrones(isochrones_gdf):
    """Merges overlapping isochrones with the same travel time into single polygons."""
    
    return isochrones_gdf.to_crs(epsg=3857).dissolve(by="level").reset_index().to_crs(epsg=4326)

def extract_travel_times(travel_data, mode, center):
    """Extracts origin coordinates and travel times for a given mode."""
    
    if NETWORK_ISOCHRONES:
        points, times = zip(*[(origin.coords[0], data['travel_time']) for origin, data in travel_data[mode]['isochrones'].items() if isinstance(origin, Point)])
        return np.array(points), np.array(times), None
    
    # Ensure that the center matches the desired key in point_isochrones
    if center not in travel_data[mode]['point_isochrones']:
        raise ValueError(f"Center {center} not found in travel data.")
    
    # Extract the points and travel times related to the specified center
    points_data = travel_data[mode]['point_isochrones'][center]
    
    # Return only the points and travel times for the given center
    points = np.array([(p.x, p.y) for p in points_data['points']])
    travel_times = np.array(points_data['travel_times'])
    
    return points, travel_times, (center.x, center.y)

def inverse_distance_weighting(points, times, grid_x, grid_y, power=2, k=8):
    """Interpolates travel times using optimized Inverse Distance Weighting (IDW)."""
    
    tree = cKDTree(points)
    distances, indices = tree.query(np.c_[grid_x.ravel(), grid_y.ravel()], k=k)
    weights = np.where(distances == 0, 1e9, 1 / (distances ** (power + np.std(distances) / np.mean(distances))))
    weights /= weights.sum(axis=1, keepdims=True)
    return (weights * times[indices]).sum(axis=1).reshape(grid_x.shape)

def fill_gaps(grid_z):
    """Fills gaps in the interpolated travel times by averaging neighboring valid values."""
    return generic_filter(grid_z, lambda w: np.nanmean(w) if np.any(~np.isnan(w)) else np.nan, size=3, mode='nearest')

def generate_isochrones(travel_data, mode, water_combined, city_poly, smooth_sigma=1.5, center=None):
    """Computes isochrones from stored travel times using IDW interpolation and contouring."""
    points, times, center = extract_travel_times(travel_data, mode, center)
    if len(points) < 4:
        raise ValueError("Not enough data points to generate isochrones.")
    
    levels = np.arange(times.min(), times.max() + 1, step=1)
    
    lon_min, lat_min, lon_max, lat_max = *points.min(axis=0), *points.max(axis=0)
    grid_x, grid_y = np.meshgrid(np.linspace(lon_min, lon_max, 100), np.linspace(lat_min, lat_max, 100))
    grid_z = inverse_distance_weighting(points, times, grid_x, grid_y, power=2, k=8)
    
    if np.all(np.isnan(grid_z)):
        raise ValueError("Interpolated grid_z contains only NaN values. Check input data.")
    
    grid_z = fill_gaps(grid_z)
    mask = np.isnan(grid_z)
    closed_mask = binary_closing(mask, structure=np.ones((3,3)))
    grid_z[closed_mask] = np.nanmean(grid_z)
    
    grid_z = gaussian_filter(grid_z, sigma=smooth_sigma)
    
    fig, ax = plt.subplots()
    contours = ax.contour(grid_x, grid_y, grid_z, levels=levels)
    plt.close(fig)
    
    isochrones = []
    min_area = 1e-5
    for level, segments in zip(levels, contours.allsegs):
        for segment in segments:
            if len(segment) > 2:
                polygon = Polygon(segment)
                
                # --- Eliminate Strange Straight Lines (Buffer & Simplify) ---
                if not polygon.is_valid:
                    polygon = polygon.buffer(0.00001)  # Fix small self-intersections
                polygon = polygon.simplify(0.0001, preserve_topology=True)
                
                # Filter out tiny polygons (slivers)
                if polygon.area < min_area:
                    continue
                
                # --- Prevent Isochrones from Crossing Water (Part 2) ---
                # Subtract water bodies so isochrones wrap around water
                polygon = polygon.difference(water_combined)
                
                polygon = polygon.intersection(city_poly)
                
                # Only add non-empty geometries
                if not polygon.is_empty:
                    isochrones.append({"level": level, "geometry": polygon})
    
    if not isochrones:
        raise ValueError("No isochrones generated. Check interpolation and contour extraction.")
    
    isochrones = merge_overlapping_isochrones(prioritize_smallest_isochrones(gpd.GeoDataFrame(isochrones, columns=["level", "geometry"], crs="EPSG:4326")))
    
    isochrones.attrs = {
        "type": 'network' if NETWORK_ISOCHRONES else 'point',
        "mode": MODE,
        "center": list(center)  # Ensure center is JSON-serializable
    }
    
    return isochrones, center