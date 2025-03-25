from variables import *

import requests
import os
import json
from bs4 import BeautifulSoup
from datetime import datetime


def filter_and_combine_json_files(dataset_keys, output_file, exclude_name=None, include_art=None):
    """Combines multiple JSON files into one, with optional filtering based on name or art."""
    if os.path.exists(output_file):
        print(f"Output file '{output_file}' already exists. No need to recreate")
        return
    
    combined_data = {
        "type": "FeatureCollection",
        "features": []
    }
    
    seen_coordinates = set()

    # Combine datasets from DATASETS (dynamic)
    for dataset_key in dataset_keys:
        # Check if dataset is in DATASETS or DATASETS_STATIC
        dataset_info = DATASETS.get(dataset_key) or DATASETS_STATIC.get(dataset_key)

        if not dataset_info:
            print(f"❌ Dataset with key '{dataset_key}' not found.")
            continue  # Skip this dataset if it's not found

        # Get the JSON file path
        file_path = dataset_info["json_file"]

        # Load and process the dataset
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

                for feature in data["features"]:
                    
                    # **Exclude 'motos' from bike parking names**
                    if dataset_key == 'bike-parking' and "properties" in feature and "moto" in (feature["properties"].get("name", "").lower()):
                        continue
                    
                    # Filter out based on 'name' attribute if exclude_name is provided
                    if exclude_name and dataset_key == 'zurich-bicycles-parking' and "properties" in feature and feature["properties"].get("name") == exclude_name:
                        continue  # Skip this feature

                    # Filter out based on 'art' attribute if include_art is provided
                    if include_art and dataset_key == 'zurich-street-parking' and "properties" in feature and feature["properties"].get("art") not in include_art:
                        continue  # Skip this feature

                    # Add only the necessary data (coordinates and geometry)
                    if "geometry" in feature:
                        coords = tuple(feature["geometry"]["coordinates"])  # Convert coordinates to tuple (hashable)

                        # Check for duplicates by coordinates
                        if coords in seen_coordinates:
                            continue  # Skip if already seen
                        else:
                            seen_coordinates.add(coords)
                            combined_data["features"].append(feature)

        except FileNotFoundError:
            print(f"❌ File not found: {file_path}")
            continue  # Skip this dataset if the file doesn't exist

    # Save the combined data into a new JSON file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=4)

    print(f"✅ Combined and filtered JSON data saved to {output_file}")

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