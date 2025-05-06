"""
Shutdown Logic for Isochrone API

This module defines cleanup and persistence routines for FastAPI shutdown events.

Responsibilities:
-----------------
- Persist updated disk-based distance cache to ensure data consistency.

Functions:
----------
- `bind_shutdown_event(app: FastAPI)`: Registers the shutdown hook with a FastAPI app.

Usage:
------
    from app.lifecycle.shutdown import bind_shutdown_event
    bind_shutdown_event(app)
"""

import logging
from fastapi import FastAPI

from app.data.distance_storage import distance_cache

logger = logging.getLogger(__name__)

def bind_shutdown_event(app: FastAPI) -> None:
    """
    Registers a shutdown event handler on the given FastAPI app.

    Args:
        app (FastAPI): The FastAPI application instance.

    Returns:
        None
    """

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        """
        Asynchronously flushes in-memory distance cache to disk on shutdown.

        Prevents loss of computed nearest-station mappings and enables cold-start continuity.

        Returns:
            None
        """
        logger.info("Shutting down: Saving distance cache to disk...")
        await distance_cache.save()
        logger.info("Distance cache persisted successfully.")