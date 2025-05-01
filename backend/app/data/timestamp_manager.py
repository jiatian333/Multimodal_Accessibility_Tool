"""
Dataset Timestamp Scraping and Persistence

This module manages timestamp data for datasets and shared mobility feeds.
It supports:
- Scraping 'Modified date' from dataset webpages.
- Reading/writing timestamps to local files.
- Tracking freshness of both static datasets and live feeds.

Components:
-----------
- `get_modified_date()`: Scrapes a date from a metadata webpage.
- `load_last_modified()` / `save_last_modified()`: Manage file-based dataset timestamps.
- `load_shared_timestamps()` / `save_shared_timestamps()`: Manage feed timestamps (UNIX format).

Storage:
--------
- `TIMESTAMP_FILE`: Used for dataset timestamps in ISO format.
- `SHARED_TIMESTAMP_FILE`: Used for shared mobility feeds (UNIX timestamps).

Usage:
------
    timestamps = load_last_modified()
    ts = get_modified_date(DATASETS["parking-facilities"]["webpage_url"])
    timestamps["parking-facilities"] = ts
    save_last_modified(timestamps)
"""


import logging
import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict

from app.core.config import TIMESTAMP_FILE, SHARED_TIMESTAMP_FILE

logger = logging.getLogger(__name__)

def get_modified_date(webpage_url: str) -> datetime:
    """
    Scrapes the 'Modified date' from a webpage and returns it as a datetime object.

    Args:
        webpage_url (str): URL of the page containing the modified timestamp.

    Returns:
        datetime: Parsed ISO 8601 timestamp.

    Raises:
        ValueError: If the expected HTML structure or date format is not found.
    """
    try:
        response = requests.get(webpage_url)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch URL: {webpage_url} — {e}")
        raise e
    
    soup = BeautifulSoup(response.text, "html.parser")

    modified_row = soup.find("th", string="Modified date")
    if not modified_row:
        logger.error("Could not find the 'Modified date' field on the page.")
        raise ValueError("Could not find the 'Modified date' field on the page.")

    modified_span = modified_row.find_next("td").find("span", class_="automatic-local-datetime")
    if not modified_span or not modified_span.has_attr("data-datetime"):
        logger.error("Could not find the modified date in the expected format.")
        raise ValueError("Could not find the modified date in the expected format.")

    modified_iso = modified_span["data-datetime"].strip()
    logger.info(f"Extracted timestamp from {webpage_url}: '{modified_iso}'")

    try:
        return datetime.fromisoformat(modified_iso.replace("+0000", "+00:00"))
    except ValueError as e:
        logger.error(f"Error parsing date '{modified_iso}' from {webpage_url}: {e}")
        raise ValueError(f"Error parsing date '{modified_iso}' from {webpage_url}: {e}")


def load_last_modified() -> Dict[str, datetime]:
    """
    Loads previously saved dataset timestamps from file.

    Returns:
        Dict[str, datetime]: Mapping of dataset keys to datetime objects.
    """
    if not os.path.exists(TIMESTAMP_FILE):
        logger.warning("No timestamp file found. Returning empty dictionary.")
        return {}

    with open(TIMESTAMP_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    timestamps = {}
    for line in lines:
        dataset, timestamp = line.strip().split(":", 1)
        try:
            timestamps[dataset] = datetime.fromisoformat(timestamp)
        except ValueError:
            logger.warning(f"Skipping invalid timestamp in file for {dataset}.")
            
    logger.debug(f"Loaded {len(timestamps)} dataset timestamps.")
    return timestamps


def save_last_modified(timestamps: Dict[str, datetime]) -> None:
    """
    Saves updated dataset timestamps to disk (ISO 8601 format).

    Args:
        timestamps (Dict[str, datetime]): Mapping of dataset keys to datetime objects.
    """
    try:
        with open(TIMESTAMP_FILE, "w", encoding="utf-8") as file:
            for dataset, ts in timestamps.items():
                file.write(f"{dataset}:{ts.isoformat()}\n")
        logger.info(f"Saved {len(timestamps)} dataset timestamps to disk.")
    except Exception as e:
        logger.error(f"Failed to save dataset timestamps: {e}", exc_info=True)
            
def load_shared_timestamps() -> Dict[str, int]:
    """
    Loads last modified timestamps for shared mobility feeds (UNIX).

    Returns:
        Dict[str, int]: Mapping of feed name to UNIX timestamp.
    """
    if not os.path.exists(SHARED_TIMESTAMP_FILE):
        logger.warning("No shared mobility timestamp file found.")
        return {}
    
    try:
        with open(SHARED_TIMESTAMP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load shared timestamps: {e}")
        return {}
        
def save_shared_timestamps(timestamps: Dict[str, int]) -> None:
    """
    Saves current shared mobility feed timestamps.

    Args:
        timestamps (Dict[str, int]): Mapping of feed names to UNIX timestamps.
    """
    try:
        with open(SHARED_TIMESTAMP_FILE, "w", encoding="utf-8") as f:
            json.dump(timestamps, f, indent=2)
        logger.debug(f"Saved {len(timestamps)} shared feed timestamps.")
    except Exception as e:
        logger.error(f"Failed to save shared timestamps: {e}", exc_info=True)