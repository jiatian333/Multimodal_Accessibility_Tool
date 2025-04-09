from variables import *
import cv2
import numpy as np
import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point, Polygon, LineString
from scipy.spatial import cKDTree
from scipy.ndimage import (
    generic_filter, gaussian_filter, grey_dilation,
    binary_dilation, binary_closing, binary_fill_holes
)
from shapely.ops import polygonize
from shapely.validation import make_valid
from affine import Affine
from skimage import measure

def validate_geometry(geom):
    """Ensure geometry is valid using buffer trick and make_valid fallback."""
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom if geom.is_valid else make_valid(geom)

def post_processing(isochrones_gdf):

    # Calculate area and sort by it (smallest first)
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
    cleaned_gdf = cleaned_gdf.to_crs(epsg=4326)
    return cleaned_gdf

def extract_travel_times(travel_data, mode, center):
    if NETWORK_ISOCHRONES:
        points, times = zip(*[(origin.coords[0], data['travel_time']) for origin, data in travel_data[mode]['isochrones'].items() if isinstance(origin, Point)])
        return np.array(points), np.array(times), None
    if center not in travel_data[mode]['point_isochrones']:
        raise ValueError(f"Center {center} not found in travel data.")
    points_data = travel_data[mode]['point_isochrones'][center]
    points = np.array([(p.x, p.y) for p in points_data['points']])
    travel_times = np.array(points_data['travel_times'])
    return points, travel_times, (center.x, center.y)

def inverse_distance_weighting(points, times, grid_x, grid_y, power=2, k=8):
    tree = cKDTree(points)
    k = min(k, len(points))
    distances, indices = tree.query(np.c_[grid_x.ravel(), grid_y.ravel()], k=k)
    weights = np.where(distances == 0, 1e-10, 1 / (distances ** (power + np.std(distances) / np.mean(distances))))
    weights /= weights.sum(axis=1, keepdims=True)
    return (weights * times[indices]).sum(axis=1).reshape(grid_x.shape)

def fill_gaps(grid_z, smooth_sigma):
    smoothed_grid = generic_filter(grid_z, lambda w: np.nanmedian(w) if np.any(~np.isnan(w)) else np.nan, size=3, mode='nearest')
    nan_mask = np.isnan(smoothed_grid)
    filled_grid = smoothed_grid.copy()
    filled_grid[nan_mask] = grey_dilation(smoothed_grid, size=(5, 5), mode='nearest')[nan_mask]
    return gaussian_filter(filled_grid, sigma=smooth_sigma)

def extract_contours(level, mask, city_mask_area, isochrones, transform):
    mask = binary_fill_holes(mask)
    mask = binary_closing(mask, structure=np.ones((5, 5)))
    mask = binary_dilation(mask, structure=np.ones((3, 3)))

    # Extract iso-valued contours using skimage
    contours = measure.find_contours(mask.astype(np.uint8), level=0.5)

    lines = [
        LineString([(c[1], c[0]) for c in contour])
        for contour in contours if len(contour) > 1
    ]

    # Polygonize the contour lines
    for poly in polygonize(lines):
        poly = Polygon([transform * (x, y) for x, y in poly.exterior.coords])

        poly = validate_geometry(poly).intersection(city_mask_area)

        if not poly.is_empty and poly.area >= 1e-6:
            isochrones.append({"level": level, "geometry": poly})
        
    return isochrones

def generate_isochrones(travel_data, mode, water_combined, city_poly, smooth_sigma=3, center=None):
    points, times, center = extract_travel_times(travel_data, mode, center)
    transform_to = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
    points = np.array([transform_to.transform(lon, lat) for lon, lat in points])
    if len(points) < 4:
        raise ValueError("Not enough data points to generate isochrones.")

    levels = np.arange(times.min(), times.max() + 1, step=1)
    
    buffer = 250
    resolution = 1000 if NETWORK_ISOCHRONES else 500
    lon_min, lat_min = points.min(axis=0)
    lon_max, lat_max = points.max(axis=0)
    grid_x, grid_y = np.meshgrid(
        np.linspace(lon_min - buffer, lon_max + buffer, resolution),
        np.linspace(lat_min - buffer, lat_max + buffer, resolution)
    )
    
    times_min, times_max = times.min(), times.max()
    normalized_times = (times - times_min) / (times_max - times_min)
    grid_z = inverse_distance_weighting(points, normalized_times, grid_x, grid_y, power=2, k=8)

    if np.all(np.isnan(grid_z)):
        raise ValueError("Interpolated grid contains only NaN values.")
    
    grid_z = fill_gaps(grid_z, smooth_sigma)
    grid_z = cv2.GaussianBlur(grid_z.astype(np.float32), (3, 3), 1)
    grid_z = grid_z * (times_max - times_min) + times_min

    city_poly_projected = gpd.GeoSeries([city_poly], crs="EPSG:4326").to_crs(epsg=2056).iloc[0]
    water_projected = gpd.GeoSeries([water_combined], crs="EPSG:4326").to_crs(epsg=2056).iloc[0]
    city_mask_area = city_poly_projected.difference(water_projected)

    xres = (lon_max + buffer - (lon_min - buffer)) / resolution
    yres = (lat_max + buffer - (lat_min - buffer)) / resolution
    transform = Affine.translation(lon_min - buffer, lat_min - buffer) * Affine.scale(xres, yres)

    isochrones = []
    epsilon = 0.01
    
    # Cover the lowest possible level
    level = levels[0]
    mask = grid_z <= level + epsilon
    isochrones = extract_contours(level, mask, city_mask_area, isochrones, transform)

    for i in range(len(levels) - 1):
        lower, upper = levels[i], levels[i + 1]
        mask = (grid_z > lower) & (grid_z <= upper + epsilon)
        isochrones = extract_contours(upper, mask, city_mask_area, isochrones, transform)

    if not isochrones:
        raise ValueError("No isochrones generated. Check data and mask processing.")
    isochrones_gdf = post_processing(gpd.GeoDataFrame(isochrones, columns=["level", "geometry"], crs="EPSG:2056"))
    isochrones_gdf.attrs = {
        "type": 'network' if NETWORK_ISOCHRONES else 'point',
        "mode": mode,
        "center": list(center) if center else None,
        "name": INPUT_STATION if center else 'null'
    }

    return isochrones_gdf, center