"""
Main Application Entry Point

This script initializes the FastAPI application used for isochrone computations.

Key Responsibilities:
---------------------
- Sets environment variables required for configuration.
- Sets up unified structured logging.
- Preloads stationary geospatial data at startup (graphs, polygons, stations).
- Instantiates the FastAPI app and registers API routes.
- Configures CORS middleware to allow browser-based cross-origin requests
  from the designated frontend application.
- Normalizes incoming HTTP request paths.

Application Lifecycle:
-----------------------
- @startup: preload critical datasets to prevent first-request latency.
- @shutdown: persist cached computations to disk for reuse across sessions.

Typical Use:
------------
This module should be specified as the app entry point when running the FastAPI server,
e.g., using `uvicorn`:

    uvicorn main:app --reload
"""
# --- Ensure environment variables are set before any dependent imports ---
from app.core.env import set_environment_variables
set_environment_variables()

from fastapi import FastAPI

from app.api.endpoints.compute import router as compute_router
from app.core.config import API_PREFIX, ROOT_PATH
from app.core.logger import setup_logging
from app.core.middleware import register_middleware
from app.lifecycle.startup import bind_startup_event
from app.lifecycle.shutdown import bind_shutdown_event

setup_logging()

app = FastAPI(root_path=ROOT_PATH)
register_middleware(app)
app.include_router(compute_router, prefix=API_PREFIX, tags=["isochrones"])

bind_startup_event(app)
bind_shutdown_event(app)