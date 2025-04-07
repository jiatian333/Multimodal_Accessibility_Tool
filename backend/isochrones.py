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
from shapely.ops import unary_union, polygonize
from shapely.validation import make_valid
from affine import Affine
from skimage import measure

def post_processing(isochrones_gdf):
    # Ensure all geometries are valid
    isochrones_gdf["geometry"] = isochrones_gdf["geometry"].apply(
        lambda geom: make_valid(geom) if not geom.is_valid else geom
    )

    # Sort by level (ascending = inner rings first)
    isochrones_gdf.sort_values("level", inplace=True)

    processed = []
    covered_area = None

    for _, row in isochrones_gdf.iterrows():
        geom = row.geometry
        # Subtract previous coverage to isolate current ring
        if covered_area:
            geom = geom.difference(covered_area)
        if not geom.is_empty and geom.is_valid and geom.area > 1e-6:
            processed.append({"level": row.level, "geometry": geom})
            covered_area = unary_union([covered_area, geom]) if covered_area else geom

    # Assemble cleaned GeoDataFrame
    cleaned_gdf = gpd.GeoDataFrame(processed, columns=["level", "geometry"], crs=isochrones_gdf.crs)

    # Optional: dissolve by level in case polygons got split
    cleaned_gdf = cleaned_gdf.dissolve(by="level").reset_index()
    cleaned_gdf['geometry'] = cleaned_gdf["geometry"].apply(lambda geom: make_valid(geom) if not geom.is_valid else geom)
    
    # Project back to WGS84 (EPSG:4326)
    cleaned_gdf = cleaned_gdf.to_crs(epsg=4326)

    # Fix any invalid geometries caused by reprojection
    cleaned_gdf["geometry"] = cleaned_gdf["geometry"].apply(
        lambda geom: geom.buffer(0) if not geom.is_valid else geom
    )

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

def generate_isochrones(travel_data, mode, water_combined, city_poly, smooth_sigma=3, center=None):
    points, times, center = extract_travel_times(travel_data, mode, center)
    transform_to = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
    points = np.array([transform_to.transform(lon, lat) for lon, lat in points])
    if len(points) < 4:
        raise ValueError("Not enough data points to generate isochrones.")

    levels = np.arange(times.min(), times.max() + 1, step=1)
    
    buffer = 250
    resolution = 500 if not NETWORK_ISOCHRONES else 1000
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

    for i in range(len(levels) - 1):
        lower, upper = levels[i], levels[i + 1]

        mask = (grid_z >= lower) & (grid_z < upper + 0.01)
        mask = binary_fill_holes(mask)
        mask = binary_closing(mask, structure=np.ones((5, 5)))
        mask = binary_dilation(mask, structure=np.ones((3, 3)))

        # Extract iso-valued contours using skimage
        contours = measure.find_contours(mask.astype(np.uint8), level=0.5)

        lines = []
        for contour in contours:
            if len(contour) < 2:
                continue
            # Flip coordinates (skimage returns [row, col], i.e., [y, x])
            line = LineString([(c[1], c[0]) for c in contour])
            lines.append(line)

        # Polygonize the contour lines
        for poly in polygonize(lines):
            poly = Polygon([transform * (x, y) for x, y in poly.exterior.coords])
            
            # Validate and clean geometry
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_valid:
                poly = make_valid(poly)

            poly = poly.intersection(city_mask_area)

            if poly.is_empty or poly.area < 1e-6:
                continue

            isochrones.append({"level": upper, "geometry": poly})

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