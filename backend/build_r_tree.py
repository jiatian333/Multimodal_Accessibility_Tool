from variables import *

import json

def build_rtree(idx):
    """Loads the combined JSON data and indexes point coordinates in dataset-specific R-trees."""
    rtree_indices = {}
    
    combined_data = {
        "bike-parking": json.load(open("data/total_bike_parking.json")),
        "parking-facilities": json.load(open("data/total_car_parking.json"))
    }

    # For each dataset in the combined data
    for dataset_name, data in combined_data.items():

        if not data.get('features'):
            print(f"Warning: No features found in {dataset_name}. Skipping...")
            continue

        # Insert each feature into the R-tree index
        for i, feature in enumerate(data["features"]):
            coords = feature["geometry"]["coordinates"]  # [longitude, latitude]
            if len(coords) == 2:  # Ensure valid coordinates
                idx.insert(i, (coords[0], coords[1], coords[0], coords[1]))  # Bounding box with identical min and max for point

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
