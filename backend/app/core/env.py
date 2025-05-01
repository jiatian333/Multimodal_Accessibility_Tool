"""
Environment Variable Configuration for Geospatial Libraries

This module defines a helper function to set key environment variables 
that improve compatibility and performance of GDAL-based libraries 
(e.g., geopandas, rasterio, fiona) on different platforms.

Function:
---------
- `set_environment_variables()`:
    - Ensures GDAL can locate its data files (important for Windows setups).
    - Caps thread usage to prevent CPU exhaustion in parallelized numpy/GDAL calls.

Usage:
------
Should be called at the very beginning of the application lifecycle,
before importing heavy geospatial libraries.

Example:
--------
    from app.core.env import set_environment_variables
    set_environment_variables()
"""


import os
import sys

def set_environment_variables() -> None:
    """
    Sets GDAL and threading-related environment variables for safe geospatial processing.
    """
    gdal_path = os.path.join(
        os.path.dirname(sys.executable),
        'Library', 'share', 'gdal'
    )
    os.environ.setdefault('GDAL_DATA', gdal_path)
    os.environ.setdefault('OMP_NUM_THREADS', '1')