"""
Distance Cache Storage
======================

This module implements a persistent disk-based cache for storing
precomputed "nearest neighbor" results between destinations and
accessible points (e.g., rental stations, parking areas).

Responsibilities:
-----------------
- Load precomputed distances on application startup.
- Save updated distance mappings during or after runtime.
- Provide quick lookup to avoid redundant network shortest-path calculations.
- Ensure consistency and durability via simple pickle serialization.

Typical Usage:
--------------
    from app.data.distance_storage import distance_cache

    nearest = distance_cache.get_cached_nearest(dest, mode)
    if nearest is None:
        # Compute and cache
        distance_cache.set_cached_nearest(dest, nearest_point, mode, distance)

Persistence:
------------
Data is automatically flushed to disk every 50 updates
or manually via FastAPI shutdown hooks.

Dependencies:
-------------
- `shapely`
- `pickle`
"""

import logging
import pickle
from typing import Dict, Optional, Tuple

from shapely.geometry import Point

from app.core.config import DISTANCE_FILE, DistanceCacheLock, TransportModes

logger = logging.getLogger(__name__)

class DistanceCache:
    """
    Disk-persistent cache for storing precomputed nearest Points.

    Each entry maps a (destination, mode) to a tuple:
    - Best nearest Point (either a rental station or parking space depending on the mode)
    - Walking distance in meters

    Designed to minimize redundant spatial computations across application runs.
    """

    def __init__(self) -> None:
        self.data: Dict[str, Dict[Point, Tuple[Point, float]]] = {}
        self.counter: int = 0
        self._load()

    def _load(self) -> None:
        """
        Loads cached distances from disk if available.
        If corrupted or missing, resets to an empty cache.

        Performs a basic structural integrity check.
        """
        if DISTANCE_FILE.exists():
            try:
                with open(DISTANCE_FILE, "rb") as f:
                    self.data = pickle.load(f)
                if not isinstance(self.data, dict):
                    logger.error("Corrupted distance cache (not a dict)")
                    raise ValueError("Corrupted distance cache (not a dict)")
            except Exception as e:
                logger.warning(f"Failed to load distance cache: {e}. Resetting cache.")
                self.data = {}
        else:
            self.data = {}

    async def save(self) -> None:
        """
        Asynchronously persists the current distance cache to disk using pickle serialization.
        """
        async with DistanceCacheLock:
            DISTANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(DISTANCE_FILE, "wb") as f:
                    pickle.dump(self.data, f)
                logger.debug("Distance cache successfully saved.")
            except Exception as e:
                logger.error(f"Failed to save distance cache at {DISTANCE_FILE}: {e}")

    def get_cached_nearest(
        self, 
        dest: Point, 
        mode: TransportModes
    ) -> Optional[Tuple[Point, float]]:
        """
        Retrieves the cached nearest Point and walking distance 
        for a given destination and mode.

        Args:
            dest (Point): Destination geometry to look up.
            mode (str): Mode string identifier (e.g., 'cycle').

        Returns:
            Optional[Tuple[Point, float]]:
                - Nearest Point (shapely.geometry.Point)
                - Distance in meters
              or None if not available.
        """
        mode_cache = self.data.get(mode, {})
        return mode_cache.get(dest)

    async def set_cached_nearest(
        self, 
        dest: Point, 
        nearest: Point, 
        mode: TransportModes, 
        distance: float
    ) -> None:
        """
        Asynchronously stores the best nearest Point 
        and associated walking distance for a given destination and mode.

        Args:
            dest (Point): Target destination Point.
            nearest (Point): Closest Point to the destination.
            mode (str): Mode identifier (e.g., 'cycle').
            distance (float): Walking distance in meters.

        Notes:
            - Automatically persists to disk every 50 insertions.
        """
        async with DistanceCacheLock:
            if mode not in self.data:
                self.data[mode] = {}
            self.data[mode][dest] = (nearest, distance)
            self.counter += 1

            if self.counter % 50 == 0:
                await self.save()
            
distance_cache = DistanceCache()