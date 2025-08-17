"""
Startup Logic for Isochrone API

This module defines startup routines that are executed once when the FastAPI app launches.

Responsibilities:
-----------------
- Preload graph, polygon, and static station data into memory.
- Eagerly load the distance cache to prevent cold-start latency.
- Initialize in-memory travel data structures shared across requests.

- Preload always-needed stationary resources (CRS, water geometries, public transport stations).
- Avoid loading heavy graphs/polygons at startup — these are loaded on-demand per request.
- Initialize in-memory travel data structures shared across requests.
- Initialize the distance cache to prevent cold-start latency.

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
        Preloads essential lightweight resources when the app launches.
        
        Loads:
        - CRS definitions (source/target coordinate systems)
        - Water geometries and spatial index
        - Public transport stations (for station lookup)
        - Distance cache for nearest POIs
        - Initializes shared travel data cache

        Heavy resources (graphs, city/canton polygons) are loaded on-demand in each request.

        Returns:
            None
        """
        logger.info("Starting up: Preloading crucial static data...")
        stationary_data.load_start()
        
        logger.info("Initializing travel data and distance cache...")
        app.state.travel_data = load_data()
        _ = distance_cache.data
        logger.info("Distance cache initialized with %d mode entries.", len(distance_cache.data))
