from variables import *

import requests
import os
from bs4 import BeautifulSoup
from datetime import datetime

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