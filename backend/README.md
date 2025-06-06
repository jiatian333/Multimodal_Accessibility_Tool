# 🚶‍♂️ Multimodal Isochrone Processing Framework

**A Python-based geospatial processing framework** for generating **network-wide and point-based isochrones** across multiple transport modes — including walking, cycling, driving, bicycle rental, e-scooter rental, and car sharing. Built for Zurich, Switzerland, but designed to be extensible to any city or region in Switzerland.

---

## 🔍 Features

- ✅ **Network-based isochrone generation** showing potential deficiencies in first- and last-mile accessibility over an entire network. Points are sampled randomly across the region, the most suitable (e.g. close access to a parking/rental station) transport station is identified and weighted according to importance. Currently available only for the city of Zurich

- ✅ **Point-based radial isochrones** displaying accessibility from a center point outwards (with a focus on train stations, but extendable to any official transit point). For areas outside the canton of Zurich, use performance mode. Note that the best results will be achieved inside the city of Zurich due to more complete input data

- ⚡ **Performance mode for on-demand fast computation** of simplified point-based radial isochrones

- 🚶‍♂️🛴🚲🚗 **Multimodal support** including walk, cycle, car, bicycle rental, e-scooters and car sharing

- ⚡ **Asynchronous & parallel processing** where possible for massive performance boost

- 💾 **Built-in data storage and recovery** to efficiently cache and reuse travel data

- 🧠 **Smart routing engine** combining the OJP API, R-tree indexing, and graph-based logic

- 🗂 **Modular architecture** for easy extension and optimization

---

---

## 🌐 Public Deployment

The backend is publicly deployed and available for use at:

🔗 **[https://geoflaskprd.ethz.ch/app/compute/](https://geoflaskprd.ethz.ch/app/compute/)**

POST requests can be sent directly to this endpoint to compute isochrones. See the [API Usage](#-api-usage) section for payload details and response formats.

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

## ⚙️ Supported Monomodal Transport Modes

| Mode             | Code             | Walking Legs     | Required POI  |
|------------------|------------------|------------------|-------------- |
| Walking          | `walk`           | —                | —             |
| Bike             | `cycle`          | ✔️ (start)       | ✔️ Parking   |
| Car              | `self-drive-car` | ✔️ (start)       | ✔️ Parking   |
| Bicycle Rental   | `bicycle_rental` | ✔️ (start & end) | ✔️ Rental    |
| E-Scooter Rental | `escooter_rental`| ✔️ (start & end) | ✔️ Rental    |
| Car Sharing      | `car_sharing`    | ✔️ (start & end) | ✔️ Rental    |

---

### 🔁 Strategy Comparison

| Feature                   | `network`      | `point` (standard) | `point` (performance)                      |
| ------------------------- | -------------- | ------------------ | -------------------------------------------|
| Monomodal only            | ✅             | ✅                | ❌ Can include PT legs                     |
| Geographic coverage       | Zurich city    | Canton of Zurich   | All of Switzerland                         |
| Accuracy                  | High           | High               | Moderate (e.g., lower radius)              |
| Speed                     | Slow           | Moderate           | ⚡ Fast (~10–25 sec)                       |
| Extra metadata            | ❌            | ❌                 | ✅ Modes, stations (if non-monomodal trip) |
| Primary use Case          | Precomputation | Precomputation     | Real-time visualization                    |

---

## 🚀 API Usage

### 🔄 Compute Isochrones

**Endpoint**: `POST /app/compute`

**Example Payload:**

```json
{
  "mode": "bicycle_rental",
  "network_isochrones": false,
  "input_station": "Zürich HB",
  "performance": true,
  "arrival_time": "2025-05-23T14:30:00Z",
  "timestamp": "2025-05-23T14:00:00Z",
  "force_update": false
}
```

**Typical Response:**
```json
{
  "status": "success",
  "type": "point",
  "station": "Zürich HB",
  "mode": "bicycle_rental",
  "reason": null,
  "error": null,
  "runtime": 0.32,
  "used_modes": ["cycle", "bus", "walk"],
  "station_names": ["Zürich, Rudolf-Brun-Brücke"]
}
```

---

## 🧠 How It Works (monomodal trips)

1. **Sample Points** — adaptively or radially, avoiding water bodies
2. **Mode-specific Routing** - using a combination of OJP API, open-source data and network graphs:
  - Walk → rental station or parking (if needed)
  - Main travel (bike, car, etc.)
  - Walk from rental station to destination (if needed) 
3. **Parse & Decode** — extract modes, times, and relevant stations
4. **Store to Cache** - avoiding redundant queries and API calls
5. **Isochrone Extraction** - builds travel time contour surfaces
6. **Database Storage** - for later spatial querying from the corresponding frontend

---

## 💾 Database Integration

Results are saved to PostgreSQL/PostGIS and disk-based cache folders:

- `save_to_database(...)`: Writes geometry + metadata
- `check_entry_exists(...)`: Checks for duplicate entries to avoid redundant calculations

---

## 🛠 Setup & Installation

```bash
# 1. Install dependencies (Python 3.9.21 recommended)
pip install -r requirements.txt

# 2. Configure environment
cp .env.template .env
# Edit .env with your values:
# API_KEY=your_api_key
# DB_USER=...
# DB_PASSWORD=...
# DB_HOST=...
# DB_PORT=...
# DB_NAME=...

# 3. Optional: Setup Git LFS for large geodata
git lfs install
git lfs track "cache/**" "data/**"

# 4. Run API locally
uvicorn main:app --reload
```

---

## 🧪 Debugging

- Full trace logs written to data/logs/debug.log
- Terminal shows structured info, warnings, errors for live tracing
- Full error handling with logging (e.g., OJP API rate limits)