"""
R-Tree Spatial Index Utilities for Transport Facilities

This module provides functions to build and query R-tree indices for static parking,
public transport, and shared mobility infrastructure such as bike, car, and scooter rentals.

Functions
---------
- build_rtree(...): Builds R-tree spatial indices from public and shared datasets.
- find_nearest(...): Queries the appropriate index to return nearby facility points.

Dependencies
------------
- json: Loads spatial coordinates from datasets.
- rtree: Efficient spatial indexing and nearest-neighbor querying.
- pandas: Handles tabular transport station data.
- app.core.config: Contains dataset paths and transport mode constants.
- app.core.data_types: Type aliasing for station structures.

Returns
-------
Dictionary of R-tree indices by mode, or nearest spatial index results.

Exceptions
----------
- FileNotFoundError, JSONDecodeError: Raised during JSON dataset loading.
- KeyError: Raised if an unknown mode is queried.
"""


import json
import logging
from typing import Dict, List, Optional, Literal, Union

import pandas as pd
from rtree.index import Index, Item

from app.core.config import (
    COMBINED_DATASETS, COMBINED_SHARED_MOBILITY, TransportModes, MODE_MAP
)
from app.core.data_types import StationDict

logger = logging.getLogger(__name__)


def build_rtree(public_stations: pd.DataFrame) -> Dict[str, Index]:
    """
    Builds R-tree spatial indices for public transport, static parking, and shared mobility modes.

    This function loads spatial data from local JSON files and inserts coordinate points
    into R-tree indices per transport mode. Supports fast spatial lookup by bounding box.

    Args:
        public_stations (pd.DataFrame): DataFrame with public transport station coordinates.

    Returns:
        Dict[str, Index]: Dictionary of R-tree indices keyed by dataset/mode.
    """
    rtree_indices: Dict[str, Index] = {}

    # --- Static datasets (bike/car parking) ---
    static_datasets: Dict[str, str] = {
        "bike-parking": COMBINED_DATASETS['json_file_bike_parking'],
        "parking-facilities": COMBINED_DATASETS['json_file_car_parking']
    }

    for dataset_name, file_path in static_datasets.items():
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            features = data.get("features", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading static dataset '{dataset_name}': {e}")
            continue

        if not features:
            logger.warning(f"No features found in {dataset_name}. Skipping...")
            continue

        rtree_idx = Index()
        for i, feature in enumerate(features):
            coords = feature.get("geometry", {}).get("coordinates")
            if coords:
                lon, lat = coords[0], coords[1]
                rtree_idx.insert(i, (lon, lat, lon, lat))

        rtree_indices[dataset_name] = rtree_idx

    # --- Public transport stations ---
    transport_rtree = Index()
    for i, row in public_stations.iterrows():
        lon, lat = row["longitude"], row["latitude"]
        transport_rtree.insert(i, (lon, lat, lon, lat))
    rtree_indices["public-transport"] = transport_rtree

    # --- Shared mobility modes (bike, escooter, car rentals) ---
    try:
        with open(COMBINED_SHARED_MOBILITY["json_file_modes"], "r", encoding="utf-8") as file:
            shared_data: Dict[str, List[StationDict]] = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load shared mobility data: {e}")
        shared_data = {}

    for mode in ["bike", "escooter", "car"]:
        stations: List[StationDict] = shared_data.get(mode, [])
        if not stations:
            logger.warning(f"No shared mobility stations found for mode '{mode}'.")
            continue

        rental_rtree = Index()
        for i, station in enumerate(stations):
            lon, lat = station["lon"], station["lat"]
            rental_rtree.insert(i, (lon, lat, lon, lat))

        rtree_indices[f"{mode}-rental"] = rental_rtree

    logger.info("Successfully built R-tree indices for transport facilities.")
    return rtree_indices


def find_nearest(
    rtree_indices: Dict[str, Index],
    lon: float,
    lat: float,
    mode: Union[TransportModes, Literal['public-transport']],
    num_results: int = 5
) -> List[Item]:
    """
    Returns the closest stations/facilities for a given mode using the appropriate R-tree index.

    This function performs a bounding box query to identify the `num_results` closest
    spatial items to the input coordinates. Works across public transport and shared mobility modes.

    Args:
        rtree_indices (Dict[str, Index]): R-tree indices built by `build_rtree`.
        lon (float): Longitude of the query point.
        lat (float): Latitude of the query point.
        mode (Union[TransportModes, Literal['public-transport']]): The type of location to search for.
        num_results (int): Number of nearest results to return.

    Returns:
        List[Item]: R-tree results for the mode or empty list if mode/index is not found.
    """
    dataset_key: Optional[str] = MODE_MAP.get(mode)
    if dataset_key not in rtree_indices:
        logger.warning(f"Requested mode '{mode}' not available in R-tree index.")
        return []

    return list(rtree_indices[dataset_key].nearest((lon, lat, lon, lat), num_results, objects=True))