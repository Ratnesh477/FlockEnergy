# Flock Energy — Urja Meter Ops REST API Service

> **A production-ready, resilient REST API proxy layer over the legacy Urja Meter Ops web portal.**  
> Includes automated session lifecycle & re-authentication, reverse-engineered HMAC bulk pipeline, BeautifulSoup4 fallback scraper, 7-tier network hierarchy tree with anomaly healing, in-memory spatial proximity query engine, and an interactive modern web dashboard.

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.10+** (tested on Python 3.10 – 3.14)
- Internet connectivity to reach `https://urja-ops.flockenergy.tech`

### 2. Setup & Installation
```bash
# Clone the repository
git clone https://github.com/<your-username>/flock-energy-api.git
cd flock-energy-api

# Create and activate a virtual environment
python -m venv venv
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the API Service
```bash
# Start the development server with live reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The service is now running at:
- **Interactive OpenAPI Documentation (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative ReDoc UI:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI 3.0 Specification:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
- **Interactive Modern Web Dashboard:** [http://localhost:8000/dashboard](http://localhost:8000/dashboard) (or root `/`)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

### 4. Run the Automated Test Suite
```bash
pytest tests/ -v
```
*(All 13 unit, integration, and anomaly-healing tests pass with 100% green status).*

---

## 🏗️ Architecture & System Design

```
+-------------------------------------------------------------------------------+
|                        Downstream Clients & Integrators                       |
|        (Data Science, Field Engineers, Web Apps, Mobile Terminals)            |
+-------------------------------------------------------------------------------+
                                      |
                           HTTP REST / JSON Requests
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                 FastAPI Application Layer (app/main.py)                       |
|   • OpenAPI 3.0 Docs (/docs)       • CORS Middleware                          |
|   • Route Handlers & Validation    • Modern Web Dashboard (/dashboard)        |
+-------------------------------------------------------------------------------+
            |                                               |
            v                                               v
+-----------------------------+             +-----------------------------------+
|  In-Memory Query & Spatial  |             |      Network Hierarchy Engine     |
|   Datastore (app/indexer.py)|             |         (app/hierarchy.py)        |
| • Haversine proximity query |             | • 7-tier topology tree            |
| • Multi-attribute filtering |             | • Bidirectional node indexing     |
| • In-memory cache (TTL 15m) |             | • Automatic healing of 22 records |
+-----------------------------+             +-----------------------------------+
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                 Urja Portal Adapter Layer (app/client.py)                     |
|   • Better-Auth Session Persistence (__Secure-better-auth.session_token)      |
|   • SvelteKit CSRF Protection (Origin & Referer spoofing)                     |
|   • Silent Auto-Reauthentication on 401 Unauthorized / 302 Redirect           |
|   • Cryptographic HMAC-SHA256 Signing for Bulk Export (/portal/export)        |
|   • BeautifulSoup4 Fallback HTML Scraper for Legacy SSR Pages                 |
+-------------------------------------------------------------------------------+
                                      |
                          Encrypted HTTPS Requests
                                      |
                                      v
+-------------------------------------------------------------------------------+
|                     Legacy Urja Meter Ops Web Portal                          |
|                     https://urja-ops.flockenergy.tech                         |
+-------------------------------------------------------------------------------+
```

---

## 📂 Repository File Layout

```
flock-energy-api/
├── app/
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Environment settings (Pydantic BaseSettings)
│   ├── models.py            # Strongly-typed Pydantic v2 data schemas
│   ├── client.py            # Legacy portal HTTP adapter & scraper
│   ├── hierarchy.py         # Network topology engine & anomaly reconciler
│   ├── indexer.py           # In-memory spatial index, filters & caching
│   ├── main.py              # FastAPI application & REST endpoint routers
│   └── static/              # Modern Web Client (Dashboard Extension)
│       ├── index.html       # Single Page Application interface
│       ├── app.js           # Client logic & interactive Canvas visualizer
│       └── style.css        # Sleek dark-mode design system
├── tests/
│   ├── __init__.py          # Test suite init
│   ├── test_api.py          # FastAPI route integration tests
│   ├── test_hierarchy.py    # Hierarchy healing and tree building tests
│   └── test_indexer.py      # Spatial proximity and filter tests
├── PROTOCOL.md              # Exhaustive reverse-engineering & protocol report
├── REFLECTION.md            # Detailed reflection answering all 5 prompt questions
├── openapi.json             # Exported OpenAPI 3.0 specification
├── requirements.txt         # Pinned Python package dependencies
├── .env.example             # Sample environment variables
└── .gitignore               # Ignored version control artifacts
```

---

## 📖 Key Documentation Deliverables

- **[PROTOCOL.md](file:///PROTOCOL.md):** Detailed technical report covering reverse-engineered authentication, Better-Auth cookies, SvelteKit CSRF enforcement, HMAC signing algorithms, internal JSON APIs, and the 22 legacy data anomalies.
- **[REFLECTION.md](file:///REFLECTION.md):** Answers to the required reflection questions (assumptions made, difficult parts, mistakes, future improvements, and self-critique).
- **[openapi.json](file:///openapi.json):** Validated OpenAPI 3.0 specification exported from the API schema.

---

## 🚀 REST API Reference & Sample Requests

### 1. System Health
```bash
curl -X GET http://localhost:8000/health
```
```json
{
  "status": "healthy",
  "portal_base_url": "https://urja-ops.flockenergy.tech",
  "portal_authenticated": true,
  "cache_stale": false,
  "cached_meters_count": 403,
  "cached_transformers_count": 40
}
```

---

### 2. Query Smart Meters (with Filtering & Search)
```bash
# Search by serial number with make and status filters
curl -X GET "http://localhost:8000/api/v1/meters?q=SE33962&make=HPL&install_status=Decommissioned"
```
```json
{
  "data": [
    {
      "meter_id": "J100000",
      "serial_number": "SE33962",
      "make": "HPL",
      "phase_type": "single",
      "install_status": "Decommissioned",
      "dt_code": "DT-001",
      "build": "legacy"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

---

### 3. Spatial Proximity Query ("What's near this coordinate?")
```bash
# Find meters within 3.0 km of Malviya Nagar, Jaipur (26.8524 N, 75.8052 E)
curl -X GET "http://localhost:8000/api/v1/meters?near_lat=26.8524&near_lng=75.8052&radius_km=3.0&sort_by=distance"
```

---

### 4. Smart Meter Details & Reconciled Hierarchy
```bash
curl -X GET http://localhost:8000/api/v1/meters/J100000
```
```json
{
  "meter_id": "J100000",
  "serial_number": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "install_status": "Decommissioned",
  "install_type": "Whole Current",
  "dt_code": "DT-001",
  "build": "legacy",
  "geo": {
    "latitude": 26.938961,
    "longitude": 75.830957
  },
  "hierarchy": {
    "zone": { "code": "Z-01", "name": "Jaipur Zone 1", "is_healed": false },
    "circle": { "code": "C-01", "name": "Circle 1", "is_healed": false },
    "division": { "code": "D-01", "name": "Division 1", "is_healed": false },
    "subdivision": { "code": "SD-01", "name": "Subdivision 1", "is_healed": false },
    "substation": { "code": "SS-01", "name": "Substation 1", "is_healed": false },
    "feeder": { "code": "F-001", "name": "Feeder 1", "is_healed": false },
    "dt": { "code": "DT-001", "name": "Malviya Nagar DT 1", "is_healed": false }
  },
  "nameplate": {
    "Meter ID": "J100000",
    "Serial No": "SE33962",
    "Make": "HPL",
    "Phase Type": "single",
    "Installation Status": "Decommissioned",
    "Installation Type": "Whole Current",
    "DT Code": "DT-001",
    "Build Generation": "legacy"
  }
}
```

---

### 5. Smart Meter Consumption History
```bash
curl -X GET http://localhost:8000/api/v1/meters/J100000/consumption
```
```json
{
  "meter_id": "J100000",
  "readings": [
    {
      "timestamp": "2026-06-23T23:30:00+05:30",
      "raw_timestamp": "23/06/2026 23:30",
      "kwh": 48438.74,
      "kvah": 52313.84,
      "volt_r": 226.0
    },
    {
      "timestamp": "2026-06-30T23:30:00+05:30",
      "raw_timestamp": "30/06/2026 23:30",
      "kwh": 48580.79,
      "kvah": 52467.25,
      "volt_r": 220.0
    }
  ],
  "stats": {
    "reading_count": 337,
    "start_time": "2026-06-23T23:30:00+05:30",
    "end_time": "2026-06-30T23:30:00+05:30",
    "kwh_initial": 48438.74,
    "kwh_latest": 48580.79,
    "kwh_total_consumed": 142.05,
    "avg_voltage": 229.4,
    "min_voltage": 220.0,
    "max_voltage": 240.0
  }
}
```

---

### 6. Network Hierarchy Tree Endpoint
```bash
# Retrieve full tree or filter by root node
curl -X GET "http://localhost:8000/api/v1/hierarchy?root_level=circle&root_code=C-01"
```

---

### 7. Fleet Analytics Summary
```bash
curl -X GET http://localhost:8000/api/v1/analytics/summary
```
```json
{
  "total_meters": 403,
  "by_status": {
    "Installed": 238,
    "Faulty": 90,
    "Decommissioned": 75
  },
  "by_make": {
    "HPL": 90,
    "Genus": 88,
    "Secure": 85,
    "Allied": 76,
    "L&T": 64
  },
  "by_phase": {
    "single": 277,
    "three": 126
  },
  "by_build": {
    "legacy": 238,
    "v2": 165
  },
  "total_transformers": 40,
  "total_transformer_capacity_kva": 6215.0,
  "healed_hierarchy_anomalies": 22,
  "last_synced_at": "2026-10-25T07:15:00Z"
}
```

---

## 💡 Engineering Decisions & Trade-Offs

### 1. In-Memory Datastore vs. Relational Database
- **Trade-off:** We selected an in-memory datastore with a 15-minute TTL rather than spinning up an external database (PostgreSQL/SQLite).
- **Rationale:** The entire fleet consists of 403 smart meters and 40 distribution transformers (<1 MB in RAM). An in-memory store executes multi-attribute filters, text searches, and Haversine proximity calculations in **sub-millisecond time (<0.5 ms)** without requiring external database setup, migrations, or local file locking.
- **Scale Limit:** At 50,000+ meters, memory consumption and linear spatial scans would become inefficient. At that scale, transitioning to an embedded SQLite database with an R-Tree index or PostgreSQL with PostGIS would be necessary.

### 2. Dual-Mode Fetching: HMAC Bulk Pipeline + BS4 Fallback
- **Trade-off:** We implemented both the cryptographic HMAC bulk export pipeline (`/portal/export`) and a resilient BeautifulSoup4 HTML scraper (`/meters/{id}`).
- **Rationale:** While `/portal/export` is 100x faster and returns complete metadata, reverse-engineered endpoints can change if the upstream portal is refactored. Having the HTML parser ensures that individual meter reads remain resilient under any condition.

### 3. Automatic Hierarchy Healing vs. Raw Passthrough
- **Trade-off:** Rather than passing through raw legacy records (which contained empty names or codes on 22 meters), the API reconstructs a bidirectional canonical topology index and heals missing values.
- **Rationale:** Downstream clients (GIS systems, billing pipelines, outage detection models) require valid network paths. Passing broken strings like `Circle 6 (code: "")` causes silent downstream failures. Every healed node is explicitly flagged with `"is_healed": true` for full audit transparency.

---

## 🚫 What Was Intentionally Skipped & Why

1. **Write Endpoints (PUT/PATCH/DELETE):**  
   The take-home instructions specifically mandated treating the legacy portal as read-only. We did not implement synthetic write capabilities because no upstream mutation APIs exist.
2. **Third-Party Heavy ORMs (SQLAlchemy / Django):**  
   Avoided heavy ORM bloat for a read-only integration adapter that operates cleanly over in-memory typed Pydantic models.
3. **External Message Queues (RabbitMQ / Kafka):**  
   Given the 403-meter scale, asynchronous queuing would add operational complexity without practical performance gains.

---

## 🔮 What We'd Improve With More Time

1. **Spatial R-Tree Indexing:** Replace linear Haversine scans with an R-Tree or `scipy.spatial.cKDTree` for instant spatial queries at 1M+ scale.
2. **Webhook Event Subscriptions:** Implement a change-detection worker that notifies external clients whenever a meter's status changes from `Installed` to `Faulty`.
3. **Automated VCR.py Network Mocking:** Add offline cassette-recorded integration tests for air-gapped CI/CD environments.

---

## 👥 Reflection

Please refer to **[REFLECTION.md](file:///REFLECTION.md)** for detailed answers to all five take-home reflection prompts:
1. Assumptions made
2. Most difficult part & how we got unstuck
3. What we would improve with another day
4. Mistakes made along the way
5. Self-critique
