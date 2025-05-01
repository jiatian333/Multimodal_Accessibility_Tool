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
- Download and combine water and river features to define unwalkable areas.
- Retrieve graphs (walk, bike, drive) and save to disk for caching.
- Load public transport station metadata and build an R-tree index.

Key Components:
---------------
- `StationaryData`: Singleton-style class that prevents redundant geodata downloads.
- `load()`: Entry point for loading all geospatial assets if not already loaded.
- `_load_*()`: Private helpers for CRS, geometry, graph, and station loading.

Usage:
------
Typical use pattern in the application:

    from app.core.cache import stationary_data
    stationary_data.load()
    G = stationary_data.G_canton
    stations = stationary_data.public_transport_stations

Dependencies:
-------------
- `osmnx`, `networkx`, `pyproj`, `shapely`, `rtree`, `pandas`, `tqdm`
"""


import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from networkx import MultiDiGraph
import osmnx as ox
import pandas as pd
from pyproj import CRS, Transformer
from rtree.index import Index
from shapely.geometry import GeometryCollection, Polygon
from tqdm import tqdm

from app.core.config import CITY_AREA, NETWORK_AREA, SOURCE_CRS, TARGET_CRS, GRAPH_DIR
from app.data.public_transport import load_public_transport_stations
from app.utils.rtree_structure import build_rtree

logger = logging.getLogger(__name__)

class StationaryData:
    """
    Preloads and caches stationary spatial data required for isochrone computations.

    This class handles:
    - CRS setup and transformation
    - City and canton polygon geometries
    - Water and river features (combined)
    - OSM walking, biking, driving network graphs for city and canton
    - Public transport station data and its R-tree spatial index

    Attributes:
        loaded (bool): Indicates whether the data has been loaded.
        source_crs (CRS): Source coordinate reference system (EPSG:4326).
        target_crs (CRS): Target CRS for Swiss projection (EPSG:2056).
        transformer (Transformer): Transformer between WGS84 and LV95.
        city_poly (Polygon): Merged polygon for the city.
        canton_poly (Polygon): Merged polygon for the canton.
        water_combined (GeometryCollection): Union of water bodies and rivers.
        G_city (MultiDiGraph): OSM walking graph for the city area.
        G_canton (MultiDiGraph): OSM walking graph for the canton area.
        public_transport_stations (pd.DataFrame): All available PT station metadata.
        idx (Index): R-tree spatial index for fast nearest-neighbor lookup.
    """
    
    def __init__(self) -> None:
        self.loaded: bool = False
        self.source_crs: Optional[CRS] = None
        self.target_crs: Optional[CRS] = None
        self.transformer: Optional[Transformer] = None

        self.city_poly: Optional[Polygon] = None
        self.canton_poly: Optional[Polygon] = None
        self.water_combined: Optional[GeometryCollection] = None

        self.G_city: Optional[MultiDiGraph] = None
        self.G_canton: Optional[MultiDiGraph] = None
        self.G_bike_city: Optional[MultiDiGraph] = None
        self.G_bike_canton: Optional[MultiDiGraph] = None
        self.G_car_city: Optional[MultiDiGraph] = None
        self.G_car_canton: Optional[MultiDiGraph] = None

        self.public_transport_stations: Optional[pd.DataFrame] = None
        self.idx: Optional[Index] = None

    def load(self) -> None:
        """
        Loads and caches all stationary data if not already loaded.
        Prevents redundant expensive API/geodata calls.
        """
        if self.loaded:
            return
        
        logger.info("Loading stationary geospatial data (graph, polygons, transformer, stations)...")
        self._load_crs()
        
        loading_tasks = [
            ("Polygons", self._load_polygons),
            ("Water Bodies", self._load_water),
            ("Walking Graphs", self._load_walking_graphs),
            ("Bike Graphs", self._load_bike_graphs),
            ("Car Graphs", self._load_car_graphs)
        ]

        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(func): name for name, func in loading_tasks}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Loading Static Data"):
                name = futures[future]
                try:
                    future.result()
                    logger.info(f"{name} loaded successfully.")
                except Exception as e:
                    logger.error(f"Error loading {name}: {e}")
                    
        self._load_stations()
        self.loaded = True
        logger.info("Stationary data preloaded.")

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

    def _load_water(self) -> None:
        """
        Loads and combines water features (natural water + waterways) for the canton area.
        This is used to exclude unwalkable water zones from sampling or graph traversal.
        """
        water = ox.features_from_place(NETWORK_AREA, {"natural": "water"}).geometry.union_all()
        rivers = ox.features_from_place(NETWORK_AREA, {"waterway": True}).geometry.union_all()
        self.water_combined = water.union(rivers)
                
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