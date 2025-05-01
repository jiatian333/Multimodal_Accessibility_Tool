"""
Parking Data Management and Update Workflow

This module manages the acquisition, deduplication, and combination of parking datasets
(e.g., bike and car parking) from various static and dynamic sources.

Functions:
----------
- filter_and_combine_json_files(...): Combines multiple filtered GeoJSON files into one.
- fetch_parking_data(...): Downloads and saves a remote JSON file from a permalink.
- check_for_updates(): Checks if new versions of the datasets are available and fetches them if needed.

Filtering:
----------
- Excludes motorcycle or irrelevant entries based on `name` or `art` attribute.
- Duplicates are identified via spatial coordinates and excluded.

Logging:
--------
All I/O and filtering actions are logged for traceability.
"""


import json
import logging
import os
import requests
from typing import List, Dict, Optional

from app.core.config import DATASETS, DATASETS_STATIC
from app.data.timestamp_manager import (
    load_last_modified,
    get_modified_date,
    save_last_modified
)

logger = logging.getLogger(__name__)

def filter_and_combine_json_files(
    dataset_keys: List[str], 
    output_file: str, 
    exclude_name: Optional[str] = None, 
    include_art: Optional[List[str]] = None
) -> None:
    """
    Combines multiple GeoJSON files into a single FeatureCollection, 
    applying optional filters for name and type ("art") and removing duplicates by coordinates.

    Args:
        dataset_keys (List[str]): List of dataset keys to include.
        output_file (str): Path to the resulting output file.
        exclude_name (str, optional): Skip features with this name (e.g., "Motorrad"). Default is None.
        include_art (List[str], optional): Allowed 'art' (types) of street parking. Default is None.
    """

    combined_data = {"type": "FeatureCollection", "features": []}
    seen_coordinates = set()

    for dataset_key in dataset_keys:
        dataset_info = DATASETS.get(dataset_key) or DATASETS_STATIC.get(dataset_key)

        if not dataset_info:
            logger.warning(f"Dataset '{dataset_key}' not found.")
            continue

        file_path = dataset_info["json_file"]
        if not os.path.exists(file_path):
            logger.error(f"Missing file: {file_path}")
            continue
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON from {file_path}: {e}")
            continue

        for feature in data.get("features", []):
            properties = feature.get("properties", {})
            coords = tuple(feature.get("geometry", {}).get("coordinates", []))

            if (
                (exclude_name=="Motorrad" and dataset_key == 'bike-parking' and "moto" in properties.get("name", "").lower()) or
                (exclude_name and dataset_key == 'zurich-bicycles-parking' and properties.get("name") == exclude_name) or
                (include_art and dataset_key == 'zurich-street-parking' and properties.get("art") not in include_art)
            ):
                continue

            if coords and coords not in seen_coordinates:
                seen_coordinates.add(coords)
                combined_data["features"].append(feature)
                
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(combined_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Filtered data saved to '{output_file}' with {len(combined_data['features'])} features.")
    except Exception as e:
        logger.error(f"Failed to save travel data to '{output_file}': {e}", exc_info=True)
    
def fetch_parking_data(permalink_url: str, json_file: str) -> Dict:
    """
    Downloads a JSON parking dataset from a permalink and saves it locally.

    Args:
        permalink_url (str): URL pointing to the JSON data.
        json_file (str): Path to save the downloaded JSON file.

    Returns:
        Dict: Parsed JSON content.
        
    Raises:
        requests.HTTPError: If the request fails.
    """
    try:
        response = requests.get(permalink_url)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch URL: {permalink_url} — {e}")
        raise e
    
    try:
        with open(json_file, "w", encoding="utf-8") as file:
            file.write(response.text)
    except Exception as e:
        logger.error(f"Failed to save dataset timestamps: {e}", exc_info=True)
        raise e
    
    logger.debug(f"Downloaded and saved: {json_file}")
    return response.json()

def check_for_updates() -> None:
    """
    Checks for dataset updates and downloads if modified.

    Compares website timestamps against local records.
    Updates local datasets and metadata file if changes are detected.
    """
    try:
        timestamps = load_last_modified()

        for dataset, info in DATASETS.items():
            logger.debug(f"Checking updates for {dataset}")
            
            try:
                website_modified_date = get_modified_date(info["webpage_url"])
            except Exception as e:
                logger.warning(f"Failed to fetch modified date for {dataset}: {e}")
                continue

            saved_modified_date = timestamps.get(dataset)

            if saved_modified_date and website_modified_date <= saved_modified_date:
                logger.debug(f"No updates for {dataset}. Using existing data.")
                continue

            logger.debug(f"New data found for {dataset}. Downloading...")
            fetch_parking_data(info["permalink_url"], info["json_file"])
            timestamps[dataset] = website_modified_date

        save_last_modified(timestamps)

    except Exception as e:
        logger.error(f"Error during parking dataset update check: {e}", exc_info=True)