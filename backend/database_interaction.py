# Sql code: 
'''CREATE TABLE isochrones (
    id SERIAL PRIMARY KEY,
    iso_type TEXT NOT NULL,   -- 'network' or 'point'
    mode TEXT NOT NULL,       -- e.g., 'walk', 'bike'
    center GEOMETRY(Point, 4326),  -- Center point for point-based isochrones
    isochrone GEOMETRY(MultiPolygon, 4326) NOT NULL,  -- The isochrone geometry
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (iso_type, mode, center)  -- Prevent duplicate entries
);'''

import psycopg2
from shapely.wkb import dumps
from shapely.geometry import MultiPolygon, Point
import geopandas as gpd

DB_CONNECTION = "dbname=your_db user=your_user password=your_password host=your_host port=your_port"

def save_isochrone_to_db(isochrones_gdf, iso_type, mode, center=None):
    """
    Saves an isochrone (GeoDataFrame) to PostgreSQL with PostGIS support.
    
    :param isochrones_gdf: A GeoDataFrame containing the isochrones.
    :param iso_type: 'network' or 'point'
    :param mode: The transport mode (e.g., 'walk', 'bike').
    :param center: A tuple (lat, lon) for point isochrones. None for network isochrones.
    """
    isochrone_geom = MultiPolygon(list(isochrones_gdf.geometry))  # Convert to MultiPolygon
    center_geom = Point(center[1], center[0]) if center else None  # Convert center to Point

    try:
        conn = psycopg2.connect(DB_CONNECTION)
        cur = conn.cursor()

        # Insert into database
        cur.execute(
            """
            INSERT INTO isochrones (iso_type, mode, center, isochrone)
            VALUES (%s, %s, ST_GeomFromWKB(%s, 4326), ST_GeomFromWKB(%s, 4326))
            ON CONFLICT (iso_type, mode, center) DO UPDATE 
            SET isochrone = EXCLUDED.isochrone, created_at = NOW();
            """,
            (iso_type, mode, dumps(center_geom) if center_geom else None, dumps(isochrone_geom))
        )

        conn.commit()
        cur.close()
        conn.close()
        print("Isochrone saved successfully.")

    except Exception as e:
        print(f"Database error: {e}")
        
def load_isochrone_from_db(iso_type, mode, center=None):
    """
    Retrieves an isochrone from the database.
    
    :param iso_type: 'network' or 'point'
    :param mode: Transport mode ('walk', 'bike', etc.)
    :param center: Tuple (lat, lon) for point-based isochrones. None for network.
    :return: A GeoDataFrame containing the stored isochrone
    """
    try:
        conn = psycopg2.connect(DB_CONNECTION)
        cur = conn.cursor()

        if center:
            cur.execute(
                """
                SELECT ST_AsBinary(isochrone) FROM isochrones 
                WHERE iso_type = %s AND mode = %s AND center = ST_GeomFromWKB(%s, 4326);
                """,
                (iso_type, mode, dumps(Point(center[1], center[0]))),
            )
        else:
            cur.execute(
                """
                SELECT ST_AsBinary(isochrone) FROM isochrones 
                WHERE iso_type = %s AND mode = %s;
                """,
                (iso_type, mode),
            )

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return gpd.GeoDataFrame(geometry=[MultiPolygon.from_wkb(row[0])], crs="EPSG:4326")
        else:
            return None

    except Exception as e:
        print(f"Database error: {e}")
        return None
    
