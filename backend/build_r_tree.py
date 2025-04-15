#!/usr/bin/env python
# coding: utf-8

from variables import COMBINED_DATASETS, COMBINED_SHARED_MOBILITY
import json
from rtree import index

def build_rtree(public_stations):
    """Builds R-tree indices for parking, public transport, and shared mobility (from combined JSON)."""
    rtree_indices = {}

    # --- Load static datasets like parking facilities ---
    datasets = {
        "bike-parking": COMBINED_DATASETS['json_file_bike_parking'],
        "parking-facilities": COMBINED_DATASETS['json_file_car_parking']
    }

    for dataset_name, file_path in datasets.items():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"❌ Error loading {dataset_name}: {e}")
            continue

        features = data.get("features", [])
        if not features:
            print(f"⚠️ Warning: No features found in {dataset_name}. Skipping...")
            continue

        rtree_idx = index.Index()
        for i, feature in enumerate(features):
            coords = feature.get("geometry", {}).get("coordinates")
            if coords:
                rtree_idx.insert(i, (coords[0], coords[1], coords[0], coords[1]))

        rtree_indices[dataset_name] = rtree_idx

    # --- Public transport points ---
    transport_rtree = index.Index()
    for i, row in public_stations.iterrows():
        transport_rtree.insert(i, (row["longitude"], row["latitude"], row["longitude"], row["latitude"]))
    rtree_indices['public-transport'] = transport_rtree

    # --- Load combined mobility JSON and build R-trees by mode ---
    try:
        with open(COMBINED_SHARED_MOBILITY["json_file_modes"], "r", encoding="utf-8") as f:
            shared_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ Error loading shared mobility data: {e}")
        shared_data = {}

    for mode in ["bike", "escooter", "car"]:
        stations = shared_data.get(mode, [])
        if not stations:
            print(f"⚠️ No stations found for mode '{mode}'.")
            continue

        rental_rtree = index.Index()
        for i, station in enumerate(stations):
            lon, lat = station["lon"], station["lat"]
            rental_rtree.insert(i, (lon, lat, lon, lat))

        rtree_indices[f"{mode}-rental"] = rental_rtree

    print("✅ R-tree indices built successfully!")
    return rtree_indices


def find_nearest(rtree_indices, lon, lat, mode, num_results=5):
    """Finds the nearest locations (parking, rentals, or public transport) based on coordinates and mode."""
    
    mode_map = {
        "cycle": "bike-parking", "escooter_rental": "escooter-rental", "bicycle_rental": "bike-rental",
        "self-drive-car": "parking-facilities", "car_sharing": "car-rental", "public-transport": "public-transport"
    }
    
    dataset_key = mode_map.get(mode)
    if dataset_key and dataset_key in rtree_indices:
        return list(rtree_indices[dataset_key].nearest((lon, lat, lon, lat), num_results, objects=True))

    return []