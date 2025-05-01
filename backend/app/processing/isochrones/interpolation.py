"""
Spatial Interpolation and Gap Filling

This module provides functionality for estimating values over a spatial grid using
Inverse Distance Weighting (IDW), and for smoothing and gap-filling in interpolated grids.

Use Cases:
----------
- Filling sparse travel time samples with smooth isochrone surfaces.
- Handling incomplete data after point-based sampling.

Functions:
----------
- inverse_distance_weighting: IDW interpolation over a 2D spatial grid.
- fill_gaps: Median + dilation + Gaussian smoothing to fill NaN holes in raster arrays.

Notes:
------
- IDW performance depends on appropriate values for `k` (neighbors) and `power`.
- NaN handling ensures robust fallback even for missing or sparse regions.
"""

import logging

import numpy as np
from scipy.spatial import cKDTree
from scipy.ndimage import (
    generic_filter, gaussian_filter, grey_dilation
)

logger = logging.getLogger(__name__)

def inverse_distance_weighting(
    points: np.ndarray,
    times: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    power: float = 2,
    k: int = 8
) -> np.ndarray:
    """
    Performs Inverse Distance Weighting (IDW) interpolation over a 2D grid.

    Args:
        points (np.ndarray): Known (x, y) coordinates (N, 2).
        times (np.ndarray): Corresponding travel times (N,).
        grid_x (np.ndarray): Meshgrid of X coordinates.
        grid_y (np.ndarray): Meshgrid of Y coordinates.
        power (float): IDW exponent; higher values reduce far-point influence.
        k (int): Number of nearest neighbors to use for interpolation.

    Returns:
        np.ndarray: Interpolated grid of travel times.
    """
    if len(points) == 0 or len(times) == 0:
        logger.error("IDW requires non-empty 'points' and 'times' arrays.")
        raise ValueError("IDW requires non-empty 'points' and 'times' arrays.")
    
    tree = cKDTree(points)
    k = min(k, len(points))

    distances, indices = tree.query(np.c_[grid_x.ravel(), grid_y.ravel()], k=k)
    with np.errstate(divide='ignore', invalid='ignore'):
        adjusted_power = power + np.std(distances) / (np.mean(distances) + 1e-10)
        weights = np.where(distances == 0, 1e-10, 1 / (distances ** adjusted_power))
    
    weights /= weights.sum(axis=1, keepdims=True)
    interpolated = (weights * times[indices]).sum(axis=1)
    return interpolated.reshape(grid_x.shape)

def fill_gaps(grid_z: np.ndarray, smooth_sigma: float) -> np.ndarray:
    """
    Fills gaps (NaNs) in a grid using a median filter, dilation, and Gaussian smoothing.

    Args:
        grid_z (np.ndarray): Interpolated grid (may contain NaNs).
        smooth_sigma (float): Standard deviation for Gaussian filter (controls blur).

    Returns:
        np.ndarray: Smoothed and gap-filled grid.
    """
    if np.all(np.isnan(grid_z)):
        return np.zeros_like(grid_z)
    
    smoothed_grid = generic_filter(
        grid_z,
        lambda w: np.nanmedian(w) if np.any(~np.isnan(w)) else np.nan,
        size=3,
        mode='nearest'
    )
    
    nan_mask = np.isnan(smoothed_grid)
    dilated_grid = grey_dilation(smoothed_grid, size=(5, 5), mode='nearest')
    smoothed_grid[nan_mask] = dilated_grid[nan_mask]
    
    return gaussian_filter(smoothed_grid, sigma=smooth_sigma)