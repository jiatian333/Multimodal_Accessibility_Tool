"""
Startup Logic for Isochrone API

This module defines startup routines that are executed once when the FastAPI app launches.

Responsibilities:
-----------------
- Preload graph, polygon, and static station data into memory.
- Eagerly load the distance cache to prevent cold-start latency.
- Initialize in-memory travel data structures shared across requests.

Functions:
----------
- `bind_startup_event(app: FastAPI)`: Registers the startup hook with a FastAPI app.

Usage:
------
    from app.lifecycle.startup import bind_startup_event
    bind_startup_event(app)
"""

import logging
from fastapi import FastAPI

from app.core.cache import stationary_data
from app.data.distance_storage import distance_cache
from app.data.travel_storage import load_data

logger = logging.getLogger(__name__)

def bind_startup_event(app: FastAPI) -> None:
    """
    Registers a startup event handler on the given FastAPI app.

    Args:
        app (FastAPI): The FastAPI application instance.

    Returns:
        None
    """

    @app.on_event("startup")
    async def startup_event() -> None:
        """
        Asynchronously preloads static data for travel-time processing at app launch.

        Loads:
        - Walking, biking, driving graphs
        - Polygon boundaries (city, canton, bodies of water)
        - CRS and public transport stations
        - Distance cache for nearest POIs
        - Initializes shared travel data cache

        Returns:
            None
        """
        logger.info("Starting up: Preloading spatial graph and station data...")
        stationary_data.load()

        logger.info("Initializing travel data and distance cache...")
        app.state.travel_data = load_data()
        _ = distance_cache.data
        logger.info("Distance cache initialized with %d mode entries.", len(distance_cache.data))
