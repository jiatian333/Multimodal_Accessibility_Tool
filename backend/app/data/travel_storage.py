"""
Travel Data Persistence Layer

This module provides functionality to persist and retrieve the multimodal travel data 
structure (`TravelData`) to/from disk. Data is serialized using Python's built-in `pickle` module.

Responsibilities:
-----------------
- Serialize the current travel state to disk after updates.
- Load the cached data if available, otherwise fall back to a clean structure.

Functions:
----------
- `save_data(travel_data)`: Serializes the current travel data using pickle.
- `load_data() -> TravelData`: Loads data if available, else initializes empty structure.

Storage:
--------
- File path is controlled via `STORED_POINTS` from `app.core.config`.
- If file is missing or corrupted, logs a warning and loads a new `TravelData` instance.

Usage:
------
    travel_data = load_data()
    save_data(travel_data)
"""


import logging
import os
import pickle

from app.core.config import STORED_POINTS, TravelDataLock
from app.core.data_types import TravelData
from app.data.travel_data import initialize_travel_data

logger = logging.getLogger(__name__)

async def save_data(travel_data: TravelData) -> None:
    """
    Asynchronously saves the travel_data dictionary to disk using pickle.

    Args:
        travel_data (TravelData): The data structure containing cached travel info.
    """
    async with TravelDataLock:
        try:
            with open(STORED_POINTS, "wb") as f:
                pickle.dump(travel_data, f)
            logger.info(f"Travel data successfully saved to '{STORED_POINTS}'.")
        except Exception as e:
            logger.error(f"Failed to save travel data to '{STORED_POINTS}': {e}", exc_info=True)

def load_data() -> TravelData:
    """
    Loads travel data from disk if available; else initializes new structure.

    Returns:
        TravelData: Loaded or newly initialized data structure.
    """
    if os.path.exists(STORED_POINTS):
        try:
            with open(STORED_POINTS, "rb") as f:
                travel_data: TravelData = pickle.load(f)
            logger.info(f"Loaded precomputed travel data from '{STORED_POINTS}'.")
            return travel_data
        except Exception as e:
            logger.warning(f"Failed to load travel data (corrupted?). Initializing fresh structure. Error: {e}")

    logger.warning("No cached travel data found. Starting with new structure.")
    return initialize_travel_data()