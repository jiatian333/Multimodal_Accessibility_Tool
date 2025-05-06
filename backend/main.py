"""
Main Application Entry Point

This script initializes the FastAPI application used for isochrone computations.

Key Responsibilities:
---------------------
- Sets environment variables required for configuration.
- Sets up unified structured logging.
- Preloads stationary geospatial data at startup (graphs, polygons, stations).
- Instantiates the FastAPI app and registers API routes.

Application Lifecycle:
-----------------------
- @startup: preload critical datasets to prevent first-request latency.
- @shutdown: persist cached computations to disk for reuse across sessions.

Typical Use:
------------
This module should be specified as the app entry point when running the FastAPI server,
e.g., using `uvicorn`:

    uvicorn app.main:app --reload
"""
# --- Ensure environment variables are set before any dependent imports ---
from app.core.env import set_environment_variables
set_environment_variables()

from fastapi import FastAPI

from app.api.endpoints.compute import router as compute_router
from app.core.config import API_PREFIX
from app.core.logger import setup_logging
from app.lifecycle.startup import bind_startup_event
from app.lifecycle.shutdown import bind_shutdown_event

setup_logging()

app = FastAPI()
app.include_router(compute_router, prefix=API_PREFIX, tags=["isochrones"])

bind_startup_event(app)
bind_shutdown_event(app)