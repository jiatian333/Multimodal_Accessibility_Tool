from variables import *
import numpy as np
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon
from scipy.spatial import cKDTree
from scipy.ndimage import binary_closing, generic_filter, gaussian_filter
from shapely.ops import unary_union

def prioritize_smallest_isochrones(isochrones_gdf):
    """Ensures isochrones with the smallest area remain on top by subtracting larger ones iteratively."""
    
    # Reproject to a projected CRS (choose appropriate CRS for your region)
    projected_gdf = isochrones_gdf.to_crs(epsg=3857)  # Web Mercator (meters)
    
    # Compute areas correctly in projected CRS
    projected_gdf["area"] = projected_gdf.geometry.area  
    projected_gdf = projected_gdf.sort_values(by="area", ascending=True)  # Smallest first

    processed_isochrones = []
    covered_area = None  # To track already covered areas

    for _, row in projected_gdf.iterrows():
        polygon = row["geometry"]

        # Subtract already covered areas (larger ones from previous iterations)
        if covered_area:
            polygon = polygon.difference(covered_area)

        # Keep only non-empty geometries
        if not polygon.is_empty:
            processed_isochrones.append({"level": row["level"], "geometry": polygon})

        # Update covered area
        covered_area = unary_union([covered_area, row["geometry"]]) if covered_area else row["geometry"]

    # Convert back to geographic CRS (EPSG:4326)
    final_gdf = gpd.GeoDataFrame(processed_isochrones, columns=["level", "geometry"], crs=projected_gdf.crs)
    final_gdf = final_gdf.to_crs(epsg=4326)  # Convert back to lat/lon

    return final_gdf

def merge_overlapping_isochrones(isochrones_gdf):
    """Merges overlapping isochrones with the same travel time into single polygons."""
    
    # Reproject to a projected CRS for accurate spatial operations
    projected_gdf = isochrones_gdf.to_crs(epsg=3857)

    # Group by travel time level and merge overlapping geometries
    merged_isochrones = (
        projected_gdf.dissolve(by="level")  # Merge within each travel time level
        .reset_index()
    )

    # Convert back to geographic CRS (EPSG:4326)
    merged_isochrones = merged_isochrones.to_crs(epsg=4326)

    return merged_isochrones

def extract_travel_times(travel_data, mode):
    """Extracts origin coordinates and travel times for a given mode."""
    points = []
    times = []
    
    if NETWORK_ISOCHRONES:
        for origin, data in travel_data[mode]['isochrones'].items():
            if isinstance(origin, Point):
                lon, lat = origin.x, origin.y
                points.append((lon, lat))
                times.append(data['travel_time'])
        return np.array(points), np.array(times), None
        
    for center, data in travel_data[mode]['point_isochrones'].items():
        center = (center.x, center.y)
        points.append([(i.x, i.y) for i in data['points']])
        times.append(data['travel_times'])
    
    return np.array(points)[0], np.array(times)[0], center

def inverse_distance_weighting(points, times, grid_x, grid_y, power=2, k=8):
    """Interpolates travel times using optimized Inverse Distance Weighting (IDW)."""
    tree = cKDTree(points)
    grid_shape = grid_x.shape
    grid_points = np.c_[grid_x.ravel(), grid_y.ravel()]
    
    distances, indices = tree.query(grid_points, k=k)  # Use more neighbors for smoother interpolation
    
    # Adaptive power factor
    adaptive_power = power + (np.std(distances) / np.mean(distances))
    
    weights = 1 / (distances ** adaptive_power)
    weights[distances == 0] = 1e9  # Prevent division by zero
    weights /= weights.sum(axis=1, keepdims=True)
    
    interpolated_times = (weights * times[indices]).sum(axis=1)
    
    return interpolated_times.reshape(grid_shape)

def fill_gaps(grid_z):
    """Fills gaps in the interpolated travel times by averaging neighboring valid values."""
    
    def average_valid_neighbors(window):
        """Helper function to compute the average of valid (non-NaN) values in the window."""
        valid_values = window[~np.isnan(window)]  # Extract non-NaN values
        if valid_values.size > 0:
            return np.mean(valid_values)  # Return the mean of valid values
        else:
            return np.nan  # If no valid neighbors, return NaN (or you can handle it differently)

    # Apply the local averaging over the grid using a sliding window (e.g., 3x3)
    grid_z_filled = generic_filter(grid_z, average_valid_neighbors, size=3, mode='nearest')
    
    return grid_z_filled

def generate_isochrones(travel_data, mode, water_combined, city_poly, smooth_sigma=1.5):
    """Computes isochrones from stored travel times using IDW interpolation and contouring."""
    points, times, center = extract_travel_times(travel_data, mode)
    
    if len(points) < 4:
        raise ValueError("Not enough data points to generate isochrones.")

    levels = np.arange(times.min(), times.max() + 1, step=1)
    
    # Define grid bounds
    lon_min, lat_min = points.min(axis=0)
    lon_max, lat_max = points.max(axis=0)

    # Create grid for interpolation
    grid_x, grid_y = np.meshgrid(
        np.linspace(lon_min, lon_max, 100),
        np.linspace(lat_min, lat_max, 100)
    )
    
    # Perform IDW interpolation
    grid_z = inverse_distance_weighting(points, times, grid_x, grid_y, power=2, k=8)
    
    # Check if all values are NaN
    if np.all(np.isnan(grid_z)):
        raise ValueError("Interpolated grid_z contains only NaN values. Check input data.")
    
    # Fill gaps
    grid_z = fill_gaps(grid_z)
    
    # Apply morphological closing to fix small holes
    mask = np.isnan(grid_z)
    closed_mask = binary_closing(mask, structure=np.ones((3,3)))
    grid_z[closed_mask] = np.nanmean(grid_z)
    
    # Apply Gaussian filter for smooth transitions
    grid_z = gaussian_filter(grid_z, sigma=smooth_sigma)

    # Generate contour lines
    fig, ax = plt.subplots()
    contours = ax.contour(grid_x, grid_y, grid_z, levels=levels)

    isochrones = []
    MIN_AREA = 1e-7  # Adjust threshold based on your coordinate system
    for level, segments in zip(levels, contours.allsegs):
        for segment in segments:
            if len(segment) > 2:
                polygon = Polygon(segment)
                
                # --- Eliminate Strange Straight Lines (Buffer & Simplify) ---
                if not polygon.is_valid:
                    polygon = polygon.buffer(0.00001)  # Fix small self-intersections
                polygon = polygon.simplify(0.0001, preserve_topology=True)
                
                # Filter out tiny polygons (slivers)
                if polygon.area < MIN_AREA:
                    continue
                
                # --- Prevent Isochrones from Crossing Water (Part 2) ---
                # Subtract water bodies so isochrones wrap around water
                polygon = polygon.difference(water_combined)
                
                polygon = polygon.intersection(city_poly)
                
                # Only add non-empty geometries
                if not polygon.is_empty:
                    isochrones.append({"level": level, "geometry": polygon})

    plt.close(fig)

    # **Debugging prints**
    if not isochrones:
        raise ValueError("No isochrones generated. Check interpolation and contour extraction.")

    # Convert to GeoDataFrame
    isochrones_gdf = gpd.GeoDataFrame(isochrones, columns=["level", "geometry"], crs="EPSG:4326")
    
    isochrones_gdf = prioritize_smallest_isochrones(isochrones_gdf)
    isochrones_gdf = merge_overlapping_isochrones(isochrones_gdf)

    return isochrones_gdf, center