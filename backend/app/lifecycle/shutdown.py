"""
Shutdown Logic for Isochrone API

This module defines cleanup and persistence routines for FastAPI shutdown events.

Responsibilities:
-----------------
- Persist updated disk-based distance cache to ensure data consistency.

Functions:
----------
- `shutdown_event()`: FastAPI-compliant shutdown hook.

Usage:
------
    Register using FastAPI’s `@app.on_event("shutdown")`.

Example:
--------
    from app.lifecycle.shutdown import shutdown_event
    app.add_event_handler("shutdown", shutdown_event)
"""

import logging

from app.data.distance_storage import distance_cache

logger = logging.getLogger(__name__)

async def shutdown_event() -> None:
    """
    Asynchronously flushes in-memory distance cache to disk on shutdown. 

    Prevents loss of computed nearest-station mappings and enables cold-start continuity.
    """
    logger.info("Shutting down: Saving distance cache to disk...")
    await distance_cache.save()
    logger.info("Distance cache persisted successfully.")
