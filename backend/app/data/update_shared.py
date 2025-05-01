"""
Shared Mobility Feed Management

This module handles downloading, processing, and combining docked and dockless shared mobility data 
(bikes, e-scooters, and car sharing) from various GBFS-compatible feeds.

Responsibilities:
-----------------
- Polls shared mobility feeds and updates locally stored JSON files if needed.
- Processes both free-floating and station-based vehicles, merging their locations.
- Maps raw vehicle data to internal transport modes ('bike', 'escooter', 'car').
- Produces a combined output file for use in downstream isochrone generation.

Key Functions:
--------------
- update_shared_mobility_data: Handles feed update logic with timestamp checks.
- merge_station_info_and_status: Joins info and status feeds into a single DataFrame.
- load_shared_mobility_locations: Extracts and formats merged vehicle location data.
- process_shared_mobility_data: Executes full pipeline and saves results.

Outputs:
--------
- Combined mobility data saved as JSON, grouped by mode with deduplicated locations.
"""


import json
import logging
from typing import List, Dict

import pandas as pd
import requests

from app.core.config import SHARED_MOBILITY_FEEDS, GBFS_MASTER_URL, COMBINED_SHARED_MOBILITY
from app.data.timestamp_manager import load_shared_timestamps, save_shared_timestamps

logger = logging.getLogger(__name__)


def update_shared_mobility_data() -> None:
    """
    Checks and updates all configured shared mobility GBFS feeds.
    """
    logger.debug("Checking shared mobility feeds...")

    try:
        gbfs = requests.get(GBFS_MASTER_URL).json()
        feeds = gbfs["data"]["en"]["feeds"]
    except Exception as e:
        logger.error(f"Error loading GBFS master feed: {e}")
        return

    local_timestamps = load_shared_timestamps()
    updated_timestamps: Dict[str, int] = {}

    for feed in feeds:
        name = feed["name"]
        if name not in SHARED_MOBILITY_FEEDS:
            continue

        url = SHARED_MOBILITY_FEEDS[name]["url"]
        file_path = SHARED_MOBILITY_FEEDS[name]["json_file"]

        try:
            logger.info(f"Fetching: {name}")
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            remote_updated = data.get("last_updated", 0)
            if local_timestamps.get(name, 0) >= remote_updated:
                logger.debug(f"Skipping '{name}': no new updates.")
                updated_timestamps[name] = local_timestamps[name]
                continue

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            updated_timestamps[name] = remote_updated
            logger.debug(f"Updated '{name}'")

        except Exception as e:
            logger.error(f"Failed to update '{name}': {e}")
            updated_timestamps[name] = local_timestamps.get(name, 0)

    save_shared_timestamps(updated_timestamps)
    logger.info("Shared mobility feeds checked and updated.")

def merge_station_info_and_status(
    info_df: pd.DataFrame,
    status_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Merges station information and status based on 'station_id' and 'provider_id'.

    Args:
        info_df (pd.DataFrame): Station information DataFrame.
        status_df (pd.DataFrame): Station status DataFrame.

    Returns:
        pd.DataFrame: Merged DataFrame with mode and location data, or empty DataFrame if merging fails.
    """
    if "provider_id" not in info_df.columns or "provider_id" not in status_df.columns:
        logger.warning("'provider_id' missing in one of the station files.")
        return pd.DataFrame()

    merged_frames = []
    providers = set(info_df["provider_id"]) & set(status_df["provider_id"])
    for provider in providers:
        info_sub = info_df[info_df["provider_id"] == provider]
        status_sub = status_df[status_df["provider_id"] == provider]
        merged = pd.merge(info_sub, status_sub, on="station_id", how="inner")
        merged["provider_id"] = provider
        merged_frames.append(merged)

    return pd.concat(merged_frames, ignore_index=True) if merged_frames else pd.DataFrame()

def load_shared_mobility_locations() -> Dict[str, List[Dict[str, float]]]:
    """
    Loads and merges free-floating and docked vehicle locations for all supported shared mobility modes.

    Returns:
        Dict[str, List[Dict[str, float]]]: Dictionary keyed by mode ('bike', 'escooter', 'car') 
                                           with lists of {'lat': float, 'lon': float} dicts.
    """
    # --- Load providers ---
    try:
        with open(SHARED_MOBILITY_FEEDS["providers"]["json_file"], "r", encoding="utf-8") as f:
            providers_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load providers file: {e}", exc_info=True)
        return {}
    
    get_mode = lambda vt: (
        "escooter" if "scooter" in vt.lower() else
        "bike" if "bike" in vt.lower() else
        "car" if "car" in vt.lower() else None
    )
    
    providers_df = pd.DataFrame(providers_data["data"]["providers"])
    providers_df["mode"] = providers_df["vehicle_type"].apply(get_mode)
    provider_modes = dict(zip(providers_df["provider_id"], providers_df["mode"]))

    # --- Free-floating vehicles ---
    try:
        with open(SHARED_MOBILITY_FEEDS["free_bike_status"]["json_file"], "r", encoding="utf-8") as f:
            bikes_data = json.load(f)
        bikes_df = pd.DataFrame(bikes_data["data"]["bikes"])
        bikes_df["mode"] = bikes_df["provider_id"].map(provider_modes)
        bikes_df = bikes_df.dropna(subset=["lat", "lon", "mode"])
    except Exception as e:
        logger.warning(f"Free-floating vehicle data could not be loaded: {e}")
        bikes_df = pd.DataFrame(columns=["lat", "lon", "mode"])

    dockless_by_mode = bikes_df.groupby("mode")[["lat", "lon"]].apply(
        lambda df: df.drop_duplicates().to_dict(orient="records")
    ).to_dict()

    # --- Dock-based stations ---
    try: 
        with open(SHARED_MOBILITY_FEEDS["station_information"]["json_file"], "r", encoding="utf-8") as f:
            station_info_data = json.load(f)
        station_info_df = pd.DataFrame(station_info_data["data"]["stations"])

        with open(SHARED_MOBILITY_FEEDS["station_status"]["json_file"], "r", encoding="utf-8") as f:
            station_status_data = json.load(f)
        station_status_df = pd.DataFrame(station_status_data["data"]["stations"])

        stations_df = merge_station_info_and_status(station_info_df, station_status_df)

        if not stations_df.empty and "provider_id" in stations_df.columns:
            stations_df = stations_df[stations_df["is_installed"] == True]
            stations_df["mode"] = stations_df["provider_id"].map(provider_modes)
            stations_df = stations_df.dropna(subset=["lat", "lon", "mode"])
        else:
            logger.warning("Could not extract docked stations (missing provider_id).")
            stations_df = pd.DataFrame(columns=["lat", "lon", "mode"])
    except Exception as e:
        logger.warning(f"Docked vehicle data could not be loaded: {e}")
        stations_df = pd.DataFrame(columns=["lat", "lon", "mode"])

    docked_by_mode = stations_df.groupby("mode")[["lat", "lon"]].apply(
        lambda df: df.drop_duplicates().to_dict(orient="records")
    ).to_dict()

    # --- Combine docked & dockless ---
    all_modes: Dict[str, List[Dict[str, float]]] = {}
    for mode in ["bike", "escooter", "car"]:
        dockless = dockless_by_mode.get(mode, [])
        docked = docked_by_mode.get(mode, [])
        combined_df = pd.DataFrame(dockless + docked)
        all_locs = combined_df.drop_duplicates(subset=["lat", "lon"]).to_dict(orient="records") if not combined_df.empty else []
        all_modes[mode] = all_locs

    return all_modes

def process_shared_mobility_data() -> None:
    """
    Downloads, processes, and saves shared mobility vehicle locations by mode.
    """
    update_shared_mobility_data()
    mode_data = load_shared_mobility_locations()
    
    try:
        with open(COMBINED_SHARED_MOBILITY["json_file_modes"], "w", encoding="utf-8") as f:
            json.dump(mode_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save final json file: {e}", exc_info=True)
        raise e

    logger.info("Vehicle mode file successfully saved.")