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

# --- Only for debugging purposes to verify the expected types for all possible situations ---
import os
from typeguard import install_import_hook

def find_python_modules(base_dir: str, base_package: str = '') -> list[str]:
    module_names = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.py') and not file.startswith('__'):
                rel_path = os.path.relpath(os.path.join(root, file), base_dir)
                module_name = os.path.splitext(rel_path)[0].replace(os.path.sep, '.')
                if base_package:
                    module_name = f"{base_package}.{module_name}"
                module_names.append(module_name)
    return module_names

modules = find_python_modules('./', base_package='')
install_import_hook(modules)



from fastapi import FastAPI

from app.api.endpoints.compute import router as compute_router
from app.core.config import API_PREFIX
from app.core.logger import setup_logging
from app.lifecycle.startup import startup_event
from app.lifecycle.shutdown import shutdown_event

setup_logging()

app = FastAPI()
app.include_router(compute_router, prefix=API_PREFIX, tags=["isochrones"])

app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)