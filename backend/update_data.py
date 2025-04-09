from variables import *

import requests
import os
import json
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime


def filter_and_combine_json_files(dataset_keys, output_file, exclude_name=None, include_art=None):
    """Combines multiple JSON files into one, filtering based on name or art."""
    
    if os.path.exists(output_file):
        print(f"✅ Output file '{output_file}' already exists.")
        return

    combined_data = {"type": "FeatureCollection", "features": []}
    seen_coordinates = set()

    for dataset_key in dataset_keys:
        dataset_info = DATASETS.get(dataset_key) or DATASETS_STATIC.get(dataset_key)

        if not dataset_info:
            print(f"❌ Dataset '{dataset_key}' not found.")
            continue

        file_path = dataset_info["json_file"]
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for feature in data.get("features", []):
                properties = feature.get("properties", {})
                coords = tuple(feature.get("geometry", {}).get("coordinates", []))

                # Filtering conditions
                if (
                    (dataset_key == 'bike-parking' and "moto" in properties.get("name", "").lower()) or
                    (exclude_name and dataset_key == 'zurich-bicycles-parking' and properties.get("name") == exclude_name) or
                    (include_art and dataset_key == 'zurich-street-parking' and properties.get("art") not in include_art)
                ):
                    continue

                # Avoid duplicates
                if coords and coords not in seen_coordinates:
                    seen_coordinates.add(coords)
                    combined_data["features"].append(feature)

        except FileNotFoundError:
            print(f"❌ Missing file: {file_path}")
            continue

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=4)

    print(f"✅ Data saved to {output_file}")

def get_modified_date(webpage_url):
    """
    Scrapes the webpage to extract the 'Modified date' from the data-datetime attribute.
    Returns a datetime object.
    """
    
    response = requests.get(webpage_url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Find the table row containing 'Modified date' and get the next <td> element
    modified_row = soup.find("th", string="Modified date")
    if not modified_row:
        raise ValueError("Could not find the 'Modified date' field on the page.")

    modified_span = modified_row.find_next("td").find("span", class_="automatic-local-datetime")

    if not modified_span or not modified_span.has_attr("data-datetime"):
        raise ValueError("Could not find the modified date in the expected format.")

    modified_iso = modified_span["data-datetime"].strip()  # Ensure no extra spaces

    # Debugging: Print extracted timestamp before conversion
    print(f"Extracted timestamp from {webpage_url}: '{modified_iso}'")

    try:
        # Ensure ISO format correctness (some sources may have formatting issues)
        return datetime.fromisoformat(modified_iso.replace("+0000", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Error parsing date '{modified_iso}' from {webpage_url}: {e}")

def load_last_modified():
    """Loads the last modified timestamps from the file."""
    
    if not os.path.exists(TIMESTAMP_FILE):
        return {}

    with open(TIMESTAMP_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    timestamps = {}
    for line in lines:
        dataset, timestamp = line.strip().split(":", 1)
        try:
            timestamps[dataset] = datetime.fromisoformat(timestamp)
        except ValueError:
            print(f"Warning: Skipping invalid timestamp in file for {dataset}.")
    
    return timestamps

def save_last_modified(timestamps):
    """Saves modified timestamps for all datasets to a file."""
    
    with open(TIMESTAMP_FILE, "w", encoding="utf-8") as file:
        for dataset, timestamp in timestamps.items():
            file.write(f"{dataset}:{timestamp.isoformat()}\n")

def fetch_parking_data(permalink_url, json_file):
    """Downloads the JSON data and saves it locally."""
    
    response = requests.get(permalink_url)
    response.raise_for_status()

    with open(json_file, "w", encoding="utf-8") as file:
        file.write(response.text)

    return response.json()

def check_for_updates():
    """Checks if the parking data has been updated and downloads it if necessary."""
    
    try:
        timestamps = load_last_modified()

        for dataset, info in DATASETS.items():
            print(f"Checking updates for {dataset}...")

            # Get the modified date from the website
            website_modified_date = get_modified_date(info["webpage_url"])
            print(f"  Website modified date: {website_modified_date}")

            # Load last saved modified date
            saved_modified_date = timestamps.get(dataset)

            # Compare dates
            if saved_modified_date and website_modified_date <= saved_modified_date:
                print(f"  No updates found for {dataset}. Using existing data.")
                continue  # Skip download if unchanged

            # Download new data
            print(f"  New data available for {dataset}! Downloading...")
            fetch_parking_data(info["permalink_url"], info["json_file"])
            timestamps[dataset] = website_modified_date  # Update timestamps
            print(f"  {dataset} data updated successfully.")

        # Save updated timestamps
        save_last_modified(timestamps)

    except Exception as e:
        print(f"Error checking updates: {e}")
        
def load_shared_timestamps():
    if os.path.exists(SHARED_TIMESTAMP_FILE):
        with open(SHARED_TIMESTAMP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_shared_timestamps(timestamps):
    with open(SHARED_TIMESTAMP_FILE, "w", encoding="utf-8") as f:
        json.dump(timestamps, f, indent=2)

def update_shared_mobility_data():
    print("🔄 Checking shared mobility feeds...")

    try:
        gbfs = requests.get(GBFS_MASTER_URL).json()
        feeds = gbfs["data"]["en"]["feeds"]
    except Exception as e:
        print(f"❌ Error loading GBFS master feed: {e}")
        return

    local_timestamps = load_shared_timestamps()
    updated_timestamps = {}

    for feed in feeds:
        name = feed["name"]
        if name not in SHARED_MOBILITY_FEEDS:
            continue  # only process defined feeds
        url = SHARED_MOBILITY_FEEDS[name]["url"]
        file_path = SHARED_MOBILITY_FEEDS[name]["json_file"]

        try:
            print(f"➡️  Fetching: {name}")
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            remote_updated = data.get("last_updated", 0)
            if local_timestamps.get(name, 0) >= remote_updated:
                print(f"  ⏩  Skipping '{name}': no new updates.")
                updated_timestamps[name] = local_timestamps[name]
                continue

            # Save feed
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            updated_timestamps[name] = remote_updated
            print(f"  ✅ Updated '{name}'")

        except Exception as e:
            print(f"  ❌ Failed to update '{name}': {e}")
            updated_timestamps[name] = local_timestamps.get(name, 0)

    save_shared_timestamps(updated_timestamps)
    print("✅ Shared mobility feeds checked and updated.")
    
def get_mode(vehicle_type: str):
    vt = vehicle_type.lower()
    if "scooter" in vt:
        return "escooter"
    elif "bike" in vt:
        return "bike"
    elif "car" in vt:
        return "car"
    return None

def merge_station_info_and_status(info_df, status_df):
    if "provider_id" not in info_df.columns or "provider_id" not in status_df.columns:
        print("⚠️ 'provider_id' missing in one of the station files.")
        return pd.DataFrame()

    merged_frames = []
    providers = set(info_df["provider_id"]) & set(status_df["provider_id"])
    for provider in providers:
        info_sub = info_df[info_df["provider_id"] == provider]
        status_sub = status_df[status_df["provider_id"] == provider]
        merged = pd.merge(info_sub, status_sub, on="station_id", how="inner")
        merged["provider_id"] = provider  # ensure retained
        merged_frames.append(merged)

    return pd.concat(merged_frames, ignore_index=True) if merged_frames else pd.DataFrame()

def load_shared_mobility_locations():
    # --- Provider modes ---
    with open(SHARED_MOBILITY_FEEDS["providers"]["json_file"], "r", encoding="utf-8") as f:
        providers_data = json.load(f)
    providers_df = pd.DataFrame(providers_data["data"]["providers"])
    providers_df["mode"] = providers_df["vehicle_type"].apply(get_mode)
    provider_modes = dict(zip(providers_df["provider_id"], providers_df["mode"]))

    # --- Free-floating vehicles ---
    with open(SHARED_MOBILITY_FEEDS["free_bike_status"]["json_file"], "r", encoding="utf-8") as f:
        free_bikes_data = json.load(f)
    bikes_df = pd.DataFrame(free_bikes_data["data"]["bikes"])

    if "provider_id" in bikes_df.columns:
        bikes_df["mode"] = bikes_df["provider_id"].map(provider_modes)
        bikes_df = bikes_df.dropna(subset=["lat", "lon", "mode"])
    else:
        print("⚠️ 'provider_id' missing in free bike data.")
        bikes_df = pd.DataFrame(columns=["lat", "lon", "mode"])

    dockless_by_mode = bikes_df.groupby("mode")[["lat", "lon"]].apply(
        lambda df: df.drop_duplicates().to_dict(orient="records")
    ).to_dict()

    # --- Dock-based stations ---
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
        print("⚠️ Could not extract docked stations.")
        stations_df = pd.DataFrame(columns=["lat", "lon", "mode"])

    docked_by_mode = stations_df.groupby("mode")[["lat", "lon"]].apply(
        lambda df: df.drop_duplicates().to_dict(orient="records")
    ).to_dict()

    # --- Combine docked & dockless ---
    all_modes = {}
    for mode in ["bike", "escooter", "car"]:
        dockless = dockless_by_mode.get(mode, [])
        docked = docked_by_mode.get(mode, [])
        combined_df = pd.DataFrame(dockless + docked)
        all_locs = combined_df.drop_duplicates(subset=["lat", "lon"]).to_dict(orient="records") if not combined_df.empty else []
        all_modes[mode] = all_locs

    return all_modes

def process_shared_mobility_data():
    
    update_shared_mobility_data()
    mode_data = load_shared_mobility_locations()

    with open(COMBINED_SHARED_MOBILITY["json_file_modes"], "w", encoding="utf-8") as f:
        json.dump(mode_data, f, indent=2)

    print("📦 Vehicle mode file successfully saved.")