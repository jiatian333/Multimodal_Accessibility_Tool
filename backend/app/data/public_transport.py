"""
Swiss Public Transport Station Loader

This module loads and filters public transport station metadata from a 
Swiss CSV dataset. It supports filtering by geographic area and transport type,
and prepares data for routing and spatial indexing.

Features:
---------
- Loads official Swiss PT stations from CSV (`service_points.csv`).
- Filters only valid "stop points" with country code "CH".
- Optionally restricts to stations within a bounding geometry (e.g., city polygon).
- Optionally restricts to train stations via `meansOfTransport` field.
- Deduplicates stations by `numberShort`, preferring newest `editionDate`.

Functions:
----------
- `load_public_transport_stations(...)`: Loads, filters, and returns station metadata.

Returns:
--------
A cleaned DataFrame with the following columns:
- `name`: Official station name
- `longitude`: X (east) coordinate in WGS84
- `latitude`: Y (north) coordinate in WGS84
- `transport_modes`: Raw textual description (may include multiple modes)

Usage:
------
    from app.data.public_transport import load_public_transport_stations

    stations_df = load_public_transport_stations(city_poly=zurich_boundary, trains=True)
"""


import logging
from typing import Optional

import pandas as pd
from shapely.geometry import Point, Polygon

from app.core.config import TRANSPORT_STATIONS

logger = logging.getLogger(__name__)

def load_public_transport_stations(
    city_poly: Optional[Polygon] = None, 
    trains: bool = False
) -> pd.DataFrame:
    """
    Loads and filters Swiss public transport stations from CSV.

    Args:
        city_poly (Polygon, optional): Bounding geometry to spatially filter stations.
        trains (bool, optional): If True, include only stations with 'TRAIN' mode.

    Returns:
        pd.DataFrame: Cleaned station dataset with name, coords, and modes.
    """
    logger.info("Loading public transport stations from CSV...")
    
    dtype_dict = {
        "abbreviation": "string",
        "districtName": "string",
        "operatingPointType": "string",
        "categories": "string",
        "operatingPointTrafficPointType": "string",
        "fotComment": "string"
    }

    df = pd.read_csv(
        TRANSPORT_STATIONS,
        sep=';',
        dtype=dtype_dict,
        header=0,
        parse_dates=["editionDate", "validFrom"]
    )
    
    logger.info(f"Loaded {len(df)} rows from source.")

    df = df[(df["isoCountryCode"] == "CH") & (df["stopPoint"] == True)]

    if trains:
        logger.debug("Filtering for only train stations")
        df = df[df["meansOfTransport"].str.contains("TRAIN", na=False)]

    df = df.sort_values(by="editionDate", ascending=False)
    df = df.drop_duplicates(subset=["numberShort"], keep="first")

    if city_poly:
        logger.debug("Applying spatial filter within city polygon.")
        df['geometry'] = df.apply(
            lambda row: Point(row['wgs84East'], row['wgs84North']),
            axis=1
        )
        df = df[df['geometry'].apply(lambda point: city_poly.contains(point))]
        df.reset_index(drop=True, inplace=True)

    stops_filtered = df[
        ["designationOfficial", "wgs84East", "wgs84North", "meansOfTransport"]
    ].rename(columns={
        "designationOfficial": "name",
        "wgs84East": "longitude",
        "wgs84North": "latitude",
        "meansOfTransport": "transport_modes"
    })

    def resolve_duplicates(group: pd.DataFrame) -> pd.Series:
        non_unknown = group[group["transport_modes"] != "UNKNOWN"]
        return non_unknown.iloc[0] if not non_unknown.empty else group.iloc[0]
    
    cleaned = stops_filtered.groupby("name", group_keys=False).apply(resolve_duplicates)
    cleaned = cleaned.reset_index(drop=True)

    logger.info(f"Final station count: {len(cleaned)}")

    return cleaned