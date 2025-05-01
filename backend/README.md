# 🚶‍♂️ Multimodal Isochrone Processing Framework

**A Python-based geospatial processing framework** for generating **network-wide and point-based isochrones** across multiple transport modes — including walking, cycling, driving, bicycle rental, e-scooter rental, and car sharing. Currently specialized for Zurich, Switzerland, but designed to be scalable to any city or region.

---

## 🔍 Features

- ✅ **Network-based isochrone generation** showing potential deficiencies in first- and last-mile accessibility over an entire network 
- ✅ **Point-based radial isochrones** displaying accessibility around points (with a focus on train stations)
- 🚶‍♂️🛴🚲🚗 **Multimodal support** (walk, cycle, car, bicycle rental, e-scooters, car sharing)  
- ⚡ **True asynchronous & parallel computation** for massive performance boost
- 📦 Built-in **storage and recovery** of geospatial travel data  
- 🧠 Smart **routing logic** using OJP API and R-tree acceleration  
- 🗂 **Modular architecture**, easy to extend or customize 

---

## 📁 Project Structure

```
app/
  ├── api/                    # FastAPI endpoint definitions
  ├── core/                   # Shared configs, environment, types
  ├── data/                   # Data persistence & cache management
  ├── lifecycle/              # Defines startup and shutdown events.  
  ├── processing/             # Isochrone algorithms & travel logic
  │    ├── travel_times/      # Async & sync multimodal routing logic
  │    ├── isochrones/        # Isochrone extraction logic
  ├── requests/               # OJP request and response handling
  ├── sampling/               # Dynamic adaptive point sampling for spatial coverage
  └── utils/                  # Helper logic: routing, filtering, R-trees

main.py                       # FastAPI app entrypoint
cache/, data/                 # Generated spatial data & logs, LFS-tracked
templates/                    # XML templates for OJP requests
```

---

## ⚙️ Supported Transport Modes

| Mode             | Code             | Walking Legs     | Required POI  |
|------------------|------------------|------------------|-------------- |
| Walking          | `walk`           | —                | —             |
| Bike             | `cycle`          | ✔️ (start)       | ✔️ Parking   |
| Car              | `self-drive-car` | ✔️ (start)       | ✔️ Parking   |
| Bicycle Rental   | `bicycle_rental` | ✔️ (start & end) | ✔️ Rental    |
| E-Scooter Rental | `escooter_rental`| ✔️ (start & end) | ✔️ Rental    |
| Car Sharing      | `car_sharing`    | ✔️ (start & end) | ✔️ Rental    |

---

## 🚀 API Usage

### 🔄 Compute Isochrones

**Endpoint**: `POST /api/compute`

**Example Payload:**

```javascript
{
  "mode": "bicycle_rental",
  "network_isochrones": true,
  "input_station": null,
  "performance": false,
  "arrival_time": "2025-04-13T14:30:00Z",
  "timestamp": "2025-04-13T14:00:00Z",
  "force_update": false
}
```

**Typical Response:**
```json
{
  "status": "success",
  "type": "network",
  "station": null,
  "mode": "bicycle_rental",
  "reason": null,
  "error": null,
  "runtime": 28.12
}
```

-  All computations use async true parallelism under the hood for maximum speed
- Embedded metadata (travel time, origin, mode)

### 📍 Strategy Comparison

| Strategy  | Description |
|-----------|-------------|
| `network` | Travel time from many random points across the full polygon |
| `point`   | Travel time from a single selected station outward |

---

## 🛠 Setup & Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment variables
cp .env.template .env
# then fill in the necessary credentials:
# API_KEY=your_api_key
# DB_USER=...
# DB_PASSWORD=...
# DB_HOST=...
# DB_PORT=...
# DB_NAME=...


# 3. Optional: Setup Git LFS for large geodata
git lfs install
git lfs track "*.shp" "*.gpkg" "cache/**"

# 4. Run API locally
uvicorn main:app --reload
```

---

## 💾 Database Integration

GeoDataFrames are persisted to a PostgreSQL/PostGIS database.

- `save_to_database(...)`: Writes geometry + metadata
- `check_entry_exists(...)`: Checks for duplicate entries to avoid redundant calculations

---

## 🧠 How It Works

1. Sample origin points via adaptive or radial logic  
2. Multimodal Routing:
  - Walk → rental station or parking (if needed)
  - Main travel (bike, car, etc.)
  - Walk from rental station to destination (if needed) 
3. Smart Caching minimizes redundant API calls
4. OJP API and walking graph used for travel time estimates  
5. Isochrone Extraction builds travel time contour surfaces
6. Database Storage for later spatial querying

---

## 🧪 Testing Strategy

- Debugging information saved to data/logs/debug.log
- Terminal shows structured info, warnings, errors for live tracing
- Full error handling with logging (e.g., OJP API rate limits)

---

## Possible Further Improvements

- Improve the performance mode (use only start and end point and call OJP directly without any additional computations)
- Location Information Search request to OJP returns way too many results even though number of results should be limited to only 1 or 2 -> find reason and solve
- Evaluate_best_candidate is the source for slowness of network isochrone computation -> find a way to further optimize and make parallel
- Progress bar in run_in_badges does not update as it should even if it is clear from debug file that the entire code executed correctly -> find reason and fix, also somehow give priority to send_request so that the code always executes this first before all other tasks when possible
