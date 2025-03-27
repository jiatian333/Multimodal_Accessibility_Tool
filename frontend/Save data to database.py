import psycopg2
from psycopg2.extensions import AsIs
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import json 
from shapely import wkb
from shapely.geometry import mapping
import ast
from sqlalchemy import create_engine

geojson_file = 'isochrones.geojson'

gdf = gpd.read_file(geojson_file)

db_credentials = {
    "user": "",
    "password": "",
    "host": "",
    "port": "",
    "dbname": ""
}

# establish database connection
conn = psycopg2.connect(**db_credentials)
cur = conn.cursor()

try:
    create_table_query_1 = """
        CREATE TABLE IF NOT EXISTS geodata (
            id SERIAL PRIMARY KEY,
            level INTEGER,
            geometry GEOMETRY
        );
    """
    
    create_table_query_2 = """
    CREATE TABLE metadata (
    id SERIAL PRIMARY KEY,       
    geodata_id INT REFERENCES geodata(id) ON DELETE CASCADE,  
    type TEXT,                    
    mode TEXT,                  
    center JSONB 
);
    """
    
    cur.execute(create_table_query_1)
    cur.execute(create_table_query_2)
    conn.commit() 
    print("Hat funktioniert!")
except Exception as e:
    conn.rollback() 
    print("Fehler beim Erstellen der Tabelle:", e)


for i in range(len(gdf["level"])):
    print(i)
    cur.execute("""
            INSERT INTO geodata (level, geometry)
            VALUES (%s, ST_GeomFromGeoJSON(%s)) RETURNING id;
        """, (int(gdf["level"][i]), json.dumps(mapping(gdf["geometry"][i]))))
    geodata_id = cur.fetchone()[0]
    meta_dic=ast.literal_eval(gdf['metadata'][i])
    print(geodata_id)
    print(gdf["metadata"][i])
    if meta_dic["center"] == None: 
        cur.execute("""
            INSERT INTO metadata (geodata_id, type, mode, center)
            VALUES (%s, %s, %s, %s);
        """, (geodata_id, meta_dic["type"], meta_dic["mode"], meta_dic["center"]))
    else:
        cur.execute("""
            INSERT INTO metadata (geodata_id, type, mode, center)
            VALUES (%s, %s, %s, %s);
        """, (geodata_id, meta_dic["type"], meta_dic["mode"], json.dumps(mapping(meta_dic["center"]))))

conn.commit()
conn.close()