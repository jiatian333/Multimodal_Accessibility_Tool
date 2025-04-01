from variables import *
import json
from rtree import index
from parameter_selection import r_tree_mode_map

def build_rtree(public_stations, shared_mobility_stations):
    """Loads the combined JSON data and indexes point coordinates in dataset-specific R-trees."""
    rtree_indices = {}
    
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
            continue  # Skip if the file is missing or malformed

        features = data.get("features", [])
        if not features:
            print(f"⚠️ Warning: No features found in {dataset_name}. Skipping...")
            continue

        rtree_idx = index.Index()
        for i, feature in enumerate(features):
            coords = feature.get("geometry", {}).get("coordinates")
            if coords:  # Ensures coordinates exist before inserting
                rtree_idx.insert(i, (coords[0], coords[1], coords[0], coords[1]))

        rtree_indices[dataset_name] = rtree_idx
        
    transport_rtree = index.Index()
    for i, row in public_stations.iterrows():
        transport_rtree.insert(i, (row["longitude"], row["latitude"], row["longitude"], row["latitude"]))
    
    rtree_indices['public-transport'] = transport_rtree

    rental_modes = ["bike", "escooter", "car"]
    for mode in rental_modes:
        # Directly use the filtered data from the `load_shared_mobility_stations` function
        stations = shared_mobility_stations.get(mode, [])
        
        if not stations:
            print(f"⚠️ Warning: No rental stations found for {mode}. Skipping...")
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
    
    mode_map = r_tree_mode_map()
    
    dataset_key = mode_map.get(mode)
    if dataset_key and dataset_key in rtree_indices:
        return list(rtree_indices[dataset_key].nearest((lon, lat, lon, lat), num_results, objects=True))

    return []