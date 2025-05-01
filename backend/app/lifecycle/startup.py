"""
Startup Logic for Isochrone API

This module defines startup routines that are executed once when the FastAPI app launches.

Responsibilities:
-----------------
- Preload graph, polygon, and static station data into memory.
- Eagerly load the distance cache to prevent cold-start latency.

Functions:
----------
- `startup_event()`: FastAPI-compliant startup hook.

Usage:
------
    Register this function using FastAPI's `@app.on_event("startup")` decorator.

Example:
--------
    from app.lifecycle.startup import startup_event
    app.add_event_handler("startup", startup_event)
"""

import logging

from app.core.cache import stationary_data
from app.data.distance_storage import distance_cache

logger = logging.getLogger(__name__)

async def startup_event() -> None:
    """
    Asynchronously preloads static data for travel-time processing at app launch.

    Loads:
    - Walking, biking, driving graphs
    - Polygon boundaries (city, canton, bodies of water)
    - CRS, public transport stations
    - Distance cache for nearest POIs

    This reduces latency for the first API request after deployment.
    """
    logger.info("Starting up: Preloading spatial graph and station data...")
    stationary_data.load()

    logger.info("Loading cached nearest-station distances into memory...")
    _ = distance_cache.data
    logger.info("Distance cache initialized with %d mode entries.", len(distance_cache.data))