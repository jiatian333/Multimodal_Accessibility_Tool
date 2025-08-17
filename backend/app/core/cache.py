"""
Stationary Geospatial Data Cache

This module provides the `StationaryData` class, responsible for one-time loading
and in-memory caching of static spatial datasets used throughout isochrone computations.

Location:
---------
- app.core.cache

Responsibilities:
-----------------
- Set up coordinate reference systems and transformations (WGS84 ↔ Swiss LV95).
- Load and merge urban/cantonal boundaries from OSM.
- Download, clean, and cache large water features for exclusion.
- Retrieve OSM-based graphs (walk, bike, drive) and cache them to disk.
- Load public transport station metadata and build an R-tree index.
- Manage memory usage by selectively loading and unloading resources.

Key Components:
---------------
- `StationaryData`: Singleton-style class preventing redundant geodata downloads.
- `load_start()`: Loads CRS, water bodies, and public transport stations at startup.
- `load_mode_resources(mode)`: Loads polygons and graphs specific to the given mode.
- `unload_mode_resources()`: Frees mode-specific resources from memory after use.
- `_load_*()`: Private helpers for CRS, polygons, water, graphs, and stations.

Usage:
------
    from app.core.cache import stationary_data
    stationary_data.load_start()
    ...
    stationary_data.load_mode_resources("cycle")
    # do computation
    stationary_data.unload_mode_resources()

Dependencies:
-------------
- `osmnx`, `networkx`, `pyproj`, `shapely`, `rtree`, `pandas`, `tqdm`
"""


import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pickle
from typing import Optional

import geopandas as gpd
from networkx import MultiDiGraph
import osmnx as ox
import pandas as pd
from pyproj import CRS, Transformer
from rtree.index import Index
from shapely.geometry import Polygon
from shapely.validation import make_valid
from tqdm import tqdm

from app.core.config import (
    CITY_AREA, NETWORK_AREA, SOURCE_CRS, 
    TARGET_CRS, GRAPH_DIR, WATER_AREA, TransportModes
)
from app.data.public_transport import load_public_transport_stations
from app.utils.rtree_structure import build_rtree

logger = logging.getLogger(__name__)

class StationaryData:
    """
    Preloads and caches stationary spatial data required for isochrone computations.

    This class handles:
    - CRS setup and transformation
    - City and canton polygon geometries
    - Water features 
    - OSM walking, biking, driving network graphs for city and canton
    - Public transport station data and its R-tree spatial index

    Attributes:
        source_crs (CRS): Source coordinate reference system (EPSG:4326).
        target_crs (CRS): Target CRS for Swiss projection (EPSG:2056).
        transformer (Transformer): Transformer between WGS84 and LV95.
        city_poly (Polygon): Merged polygon for the city.
        canton_poly (Polygon): Merged polygon for the canton.
        water_gdf (GeoDataFrame): Cleaned water features (projected).
        water_sindex (gpd.sindex.SpatialIndex): Spatial index for fast water intersection checks.
        G_city (MultiDiGraph): City graph for walking.
        G_canton (MultiDiGraph): Canton graph for walking.
        G_bike_city (MultiDiGraph): City graph for biking.
        G_bike_canton (MultiDiGraph): Canton graph for biking.
        G_car_city (MultiDiGraph): City graph for driving.
        G_car_canton (MultiDiGraph): Canton graph for driving.
        public_transport_stations (pd.DataFrame): All available PT station metadata.
        idx (Index): R-tree spatial index for fast nearest-neighbor lookup.
    """
    
    def __init__(self) -> None:
        self.source_crs: Optional[CRS] = None
        self.target_crs: Optional[CRS] = None
        self.transformer: Optional[Transformer] = None

        self.city_poly: Optional[Polygon] = None
        self.canton_poly: Optional[Polygon] = None
        self.water_gdf: Optional[gpd.GeoDataFrame] = None
        self.water_sindex: Optional[gpd.sindex.SpatialIndex] = None

        self.G_city: Optional[MultiDiGraph] = None
        self.G_canton: Optional[MultiDiGraph] = None
        self.G_bike_city: Optional[MultiDiGraph] = None
        self.G_bike_canton: Optional[MultiDiGraph] = None
        self.G_car_city: Optional[MultiDiGraph] = None
        self.G_car_canton: Optional[MultiDiGraph] = None

        self.public_transport_stations: Optional[pd.DataFrame] = None
        self.idx: Optional[Index] = None
        
    def load_start(self) -> None:
        """
        Load CRS, water geometries, and public transport stations at startup.

        This is called once at application startup and ensures that the minimum
        always-required resources are preloaded and kept in memory.

        Loads:
            - CRS transformer
            - Water bodies
            - Public transport stations and R-tree index
        """
        if self.water_gdf is not None:
            return

        logger.info("Loading startup resources (CRS, water geometries, stations)...")
        self._load_crs()

        tasks = [("Water Bodies", self._load_water), ("Stations", self._load_stations)]
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(func): name for name, func in tasks}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Loading Startup Resources"):
                name = futures[future]
                try:
                    future.result()
                    logger.info(f"{name} loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading {name}: {e}")
        
    def load_mode_resources(self, mode: TransportModes) -> None:        
        """
        Load polygons and graphs required for isochrone computation of a given mode.
        This method is called only when a non-performance computation is requested.

        Args:
            mode (TransportModes): Transport mode identifier. Determines which graphs to load.
                - "cycle", "escooter_rental", "bicycle_rental": Loads bike graphs.
                - "self-drive-car", "car_sharing": Loads car graphs.
                - All modes: Load polygons and walking graphs.
        """
        logger.info(f"Loading polygons and graphs for mode: {mode}")

        tasks = [("Polygons", self._load_polygons), ("Walking Graphs", self._load_walking_graphs)]
        if mode in ["cycle", "escooter_rental", "bicycle_rental"]:
            tasks.append(("Bike Graphs", self._load_bike_graphs))
        elif mode in ["self-drive-car", "car_sharing"]:
            tasks.append(("Car Graphs", self._load_car_graphs))

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(func): name for name, func in tasks}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Loading Mode Resources"):
                name = futures[future]
                try:
                    future.result()
                    logger.info(f"{name} loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading {name}: {e}")

    def unload_mode_resources(self) -> None:
        """
        Frees mode-specific resources from memory.

        Clears city/canton polygons and all graph objects from memory to reduce
        resource usage. Water bodies, CRS, and stations remain cached for reuse.
        """
        
        self.city_poly = None
        self.canton_poly = None
        self.G_city = None
        self.G_canton = None
        self.G_bike_city = None
        self.G_bike_canton = None
        self.G_car_city = None
        self.G_car_canton = None

    def _load_crs(self) -> None:
        """
        Sets up source and target CRS and initializes the coordinate transformer.
        - Source: EPSG 4326 (WGS84)
        - Target: EPSG 2056 (Swiss LV95)
        """
        self.source_crs = CRS.from_epsg(SOURCE_CRS)
        self.target_crs = CRS.from_epsg(TARGET_CRS)
        self.transformer = Transformer.from_crs(self.source_crs, self.target_crs, always_xy=True)

    def _load_polygons(self) -> None:
        """
        Loads and merges the city and canton polygons defined by OSM place names.
        """
        self.city_poly = ox.geocode_to_gdf(CITY_AREA).geometry.union_all()
        self.canton_poly = ox.geocode_to_gdf(NETWORK_AREA).geometry.union_all()

    def _load_water(self, file: Path = GRAPH_DIR / "cached_water.pkl") -> None:
        """
        Loads and caches valid large water bodies (Polygon and MultiPolygon only).
        If cached data exists, load from disk. Otherwise, fetch from OSM and cache it.
        This is used to exclude unwalkable water zones from sampling or graph traversal.
        
        Args:
            file (Path): Path to local cache file (.pkl).
        """
        if file.exists():
            with open(file, "rb") as f:
                combined = pickle.load(f)
                self.water_gdf = gpd.GeoDataFrame(geometry=combined, crs=self.source_crs).to_crs(self.target_crs)
                self.water_sindex = self.water_gdf.sindex
            return
        
        try:
            water = ox.features_from_place(WATER_AREA, {"natural": "water"}).geometry
            combined = water[water.geom_type.isin(["Polygon", "MultiPolygon"])]
            combined = combined[~combined.is_empty & combined.notnull()]
            combined = combined[combined.is_valid]
            combined = combined.apply(make_valid)
            combined = combined.reset_index(drop=True)
            self.water_gdf = gpd.GeoDataFrame(geometry=combined, crs=self.source_crs).to_crs(self.target_crs)
            self.water_sindex = self.water_gdf.sindex

            with open(file, "wb") as f:
                pickle.dump(list(combined.geometry), f)

            logger.info("Water features processed and cached locally.")

        except Exception as e:
            logger.error(f"Error while loading or saving water features: {e}")
            raise
                
    def _load_graph_generic(self, city_file: str, canton_file: str, 
                             city_area: str, canton_area: str, 
                             network_type: str) -> tuple[MultiDiGraph, MultiDiGraph]:
        """
        Loads or downloads and caches OSM network graphs for a specified transport mode.

        This utility checks if pre-saved GraphML files exist in the cache directory.
        If missing, it downloads fresh graphs from OpenStreetMap, saves them, and loads them
        into memory.

        Args:
            city_file (str): Filename for the city graph (relative to GRAPH_DIR).
            canton_file (str): Filename for the canton-wide graph (relative to GRAPH_DIR).
            city_area (str): Place name or area string for the city boundary.
            canton_area (str): Place name or area string for the canton boundary.
            network_type (str): Type of OSM network ("walk", "bike", "drive", etc.).

        Returns:
            Tuple[MultiDiGraph, MultiDiGraph]: Loaded city and canton graphs as NetworkX MultiDiGraphs.
        """
        city_path = GRAPH_DIR / city_file
        if city_path.exists():
            G_city = ox.load_graphml(city_path)
            logger.debug(f"Loaded cached {network_type} graph for city.")
        else:
            G_city = ox.graph_from_place(city_area, network_type=network_type)
            ox.save_graphml(G_city, filepath=city_path)
            logger.debug(f"Downloaded and cached {network_type} graph for city.")
            
        canton_path = GRAPH_DIR / canton_file
        if canton_path.exists():
            G_canton = ox.load_graphml(canton_path)
            logger.debug(f"Loaded cached {network_type} graph for canton.")
        else:
            G_canton = ox.graph_from_place(canton_area, network_type=network_type)
            ox.save_graphml(G_canton, filepath=canton_path)
            logger.debug(f"Downloaded and cached {network_type} graph for canton.")

        return G_city, G_canton
                
    def _load_walking_graphs(self) -> None:
        """
        Downloads walking graphs (MultiDiGraph) for city and canton areas from OSM.
        Used for travel time computations and nearest-neighbor routing.
        Saves graphs to disk after first download to avoid future re-downloads.
        """
        self.G_city, self.G_canton = self._load_graph_generic(
            "graph_city.graphml", "graph_canton.graphml",
            CITY_AREA, NETWORK_AREA,
            network_type="walk"
        )
                
    def _load_bike_graphs(self) -> None:
        """
        Loads or downloads bicycle graphs (MultiDiGraph) for city and canton areas.
        Used for nearest-neighbor routing and intersection calculation.
        Caches graphs after first download to avoid repeated OSM queries.
        """
        self.G_bike_city, self.G_bike_canton = self._load_graph_generic(
            "graph_city_bike.graphml", "graph_canton_bike.graphml",
            CITY_AREA, NETWORK_AREA,
            network_type="bike"
        )

    def _load_car_graphs(self) -> None:
        """
        Loads or downloads car driving graphs (MultiDiGraph) for city and canton areas.
        Used for nearest-neighbor routing and intersection calculation.
        Caches graphs after first download to avoid repeated OSM queries.
        """
        self.G_car_city, self.G_car_canton = self._load_graph_generic(
            "graph_city_car.graphml", "graph_canton_car.graphml",
            CITY_AREA, NETWORK_AREA,
            network_type="drive"
        )

    def _load_stations(self) -> None:
        """
        Loads public transport station metadata and builds a spatial index (R-tree).
        This allows efficient lookup of the nearest station to any point.
        """
        self.public_transport_stations = load_public_transport_stations()
        self.idx = build_rtree(self.public_transport_stations)

stationary_data: StationaryData = StationaryData()