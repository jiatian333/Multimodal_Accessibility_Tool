from variables import *

import json
import os

def build_rtree(idx):
    """Loads JSON files and indexes point coordinates in dataset-specific R-trees."""
    rtree_indices = {}

    for dataset_name, values in DATASETS.items():
        file_path = values['json_file']
        if not os.path.exists(file_path):
            print(f"Warning: Data file not found {file_path}. Skipping...")
            continue

        # Load JSON data
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for i, feature in enumerate(data["features"]):
            coords = feature["geometry"]["coordinates"]  # [longitude, latitude]
            idx.insert(i, (coords[0], coords[1], coords[0], coords[1]))

        rtree_indices[dataset_name] = idx

    print("✅ R-tree indices built successfully!")
    return rtree_indices


def find_nearest(rtree_indices, lon, lat, mode, num_results=5):
    """Finds the nearest parking spots based on coordinates and MODE."""
    dataset_key = None
    if mode in ["cycle", "escooter_rental", "bicycle_rental"]:
        dataset_key = "bike-parking"
    elif mode in ["self-drive-car", "car_sharing"]:
        dataset_key = "parking-facilities"

    if dataset_key and dataset_key in rtree_indices:
        return list(rtree_indices[dataset_key].nearest((lon, lat, lon, lat), num_results, objects=True))
    
    return []
