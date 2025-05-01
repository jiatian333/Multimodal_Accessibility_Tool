"""
Database Persistence Layer for Isochrone Geometries

This module provides two main functions to interact with a PostgreSQL/PostGIS 
database, used to store and retrieve isochrone geometries and associated metadata.

Responsibilities:
-----------------
- Save GeoDataFrames with isochrone results to a `geodata` table.
- Check whether a matching geospatial record already exists to prevent duplicates.

Key Functions:
--------------
- `save_to_database(gdf: GeoDataFrame)`: Writes isochrone geometries and metadata.
- `check_entry_exists(...)`: Returns True if a record with given type/mode/name exists.

Requirements:
-------------
- PostgreSQL/PostGIS database connection via credentials in `.env`.
- Required table (`geodata`) is auto-created on first write.
- Expects `gdf.attrs` to contain: `type`, `mode`, `center`, `name`.

Usage:
------
    from app.data.db_operations import save_to_database, check_entry_exists

    if not check_entry_exists("point", "walk", "Zürich HB"):
        save_to_database(my_isochrones_gdf)

Logging:
--------
- Logs all major I/O operations and errors with full tracebacks.
"""


import json
import logging

import psycopg2
from geopandas import GeoDataFrame
from psycopg2.extras import execute_values
from shapely.geometry import mapping

from app.core.config import DB_CREDENTIALS, TransportModes

logger = logging.getLogger(__name__)


def save_to_database(gdf: GeoDataFrame) -> None:
    """
    Saves a GeoDataFrame with associated metadata to a PostgreSQL/PostGIS database.

    Args:
        gdf (GeoDataFrame): GeoDataFrame containing isochrone geometries and associated metadata.

    Raises:
        psycopg2.DatabaseError: If any database operation fails.
    """

    with psycopg2.connect(**DB_CREDENTIALS) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS geodata (
                        id SERIAL PRIMARY KEY,
                        level INTEGER,
                        geometry GEOMETRY,
                        type TEXT,
                        mode TEXT,
                        coords_center JSONB,
                        name TEXT
                    );
                """)
                conn.commit()

                meta_dic = gdf.attrs
                required_keys = ["type", "mode", "center", "name"]
                for key in required_keys:
                    if key not in meta_dic:
                        raise ValueError(f"Missing metadata attribute in gdf.attrs: {key}")

                
                geodata_values = [
                    (
                        int(level),
                        json.dumps(mapping(geometry)),
                        meta_dic["type"],
                        meta_dic["mode"],
                        json.dumps(meta_dic["center"]),
                        meta_dic["name"]
                    )
                    for level, geometry in zip(gdf["level"], gdf["geometry"])
                ]

                insert_query = """
                    INSERT INTO geodata (level, geometry, type, mode, coords_center, name)
                    VALUES %s;
                """
                execute_values(cur, insert_query, geodata_values)
                conn.commit()

                logger.info(f"Inserted {len(geodata_values)} isochrone entries into database.")

            except Exception as e:
                conn.rollback()
                logger.error(f"Error while uploading isochrones to database: {e}", exc_info=True)
                
def check_entry_exists(
    type_: str,
    mode: TransportModes,
    name: str
) -> bool:
    """
    Checks if a geodata record exists in the database based on type, mode, and name.

    Args:
        type_ (str): Isochrone type ("network" or "point").
        mode (TransportModes): Transport mode (e.g., 'walk', 'cycle').
        name (str): Station name if point isochrone.

    Returns:
        bool: True if a matching record exists, False otherwise.
    """
    try:

        with psycopg2.connect(**DB_CREDENTIALS) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM geodata
                        WHERE type = %s AND mode = %s AND name = %s
                    );
                """, (type_, mode, name))
                exists = cur.fetchone()[0]
                logger.info(f"Checked DB for ({type_}, {mode}, {name}) → Exists: {exists}")
                return exists

    except Exception as e:
        logger.error(f"Error while checking for existing geodata entry: {e}", exc_info=True)
        return False