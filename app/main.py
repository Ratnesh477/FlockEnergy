import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.client import portal_client
from app.config import settings
from app.indexer import data_store
from app.models import (
    AnalyticsSummary,
    AuthStatusResponse,
    GeoLocation,
    HierarchyTreeNode,
    LoginRequest,
    MeterConsumptionResponse,
    MeterDetail,
    MeterSummary,
    PaginatedResponse,
    TransformerDetail,
    TransformerSummary,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("urja_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle manager."""
    logger.info("Initializing Flock Energy Urja Meter Ops API Service...")
    # Pre-warm portal session and local index in background/startup
    try:
        portal_client._ensure_authenticated()
        data_store.ensure_synced()
        logger.info("Portal connection established and initial dataset indexed successfully.")
    except Exception as exc:
        logger.warning(f"Initial sync warning (will retry on request): {exc}")
    yield
    logger.info("Shutting down Urja Meter Ops API Service.")


app = FastAPI(
    title="Flock Energy - Urja Meter Ops API",
    version="1.0.0",
    description=(
        "Clean, resilient, modern REST API proxy layer over legacy Urja Meter Ops portal.\n\n"
        "Features:\n"
        "- Automated Better-Auth session persistence & seamless re-authentication\n"
        "- Reverse-engineered internal JSON and HMAC-SHA256 signed export APIs\n"
        "- BeautifulSoup4 fallback HTML scraper for legacy pages\n"
        "- 7-tier distribution network hierarchy tree with automatic anomaly healing\n"
        "- In-memory query engine supporting multi-attribute & geographic proximity search\n"
        "- Normalized timestamps (ISO 8601) and parsed floating-point metrics"
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for downstream frontend clients and web dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for the Modern Web Client Dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# -----------------------------------------------------------------------------
# System & Root Endpoints
# -----------------------------------------------------------------------------

@app.get(
    "/",
    summary="Root Endpoint",
    description="Serves the Modern Interactive Web Dashboard or redirects to interactive API docs.",
    include_in_schema=False,
)
def root(accept: Optional[str] = None):
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/docs")


@app.get(
    "/dashboard",
    summary="Interactive Modern Web Dashboard",
    description="Modern web app presenting smart meters, consumption charts, and hierarchy explorer.",
    include_in_schema=False,
)
def dashboard():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Modern Dashboard</h1><p>Static index.html not found.</p>")


@app.get(
    "/health",
    summary="Service Health Check",
    tags=["System"],
    response_description="Service status and legacy portal connectivity",
)
def health_check():
    """Verify API service health, legacy portal reachability, and cache freshness."""
    logged_in = portal_client.is_logged_in()
    stale = data_store.is_stale()
    meter_count = len(data_store._raw_meters)
    return {
        "status": "healthy",
        "portal_base_url": portal_client.base_url,
        "portal_authenticated": logged_in,
        "cache_stale": stale,
        "cached_meters_count": meter_count,
        "cached_transformers_count": len(data_store._raw_dts),
    }


# -----------------------------------------------------------------------------
# Authentication Endpoints
# -----------------------------------------------------------------------------

@app.post(
    "/api/v1/auth/login",
    response_model=AuthStatusResponse,
    summary="Authenticate with Legacy Portal",
    tags=["Authentication"],
    description="Explicitly authenticate or refresh credentials with the Urja Meter Ops portal.",
)
def login(payload: Optional[LoginRequest] = None):
    username = payload.username if payload else None
    password = payload.password if payload else None
    
    success = portal_client.login(username=username, password=password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to authenticate with legacy portal using provided credentials."
        )
    
    # Warm data store upon explicit login
    try:
        data_store.ensure_synced(force=True)
    except Exception as e:
        logger.warning(f"Sync error during login: {e}")

    return AuthStatusResponse(
        authenticated=True,
        session_token_present=portal_client.is_logged_in(),
        portal_url=portal_client.base_url,
        account_email=username or portal_client.username,
    )


@app.get(
    "/api/v1/auth/status",
    response_model=AuthStatusResponse,
    summary="Authentication Status",
    tags=["Authentication"],
    description="Check whether the API currently holds an active Better-Auth session cookie.",
)
def auth_status():
    return AuthStatusResponse(
        authenticated=portal_client._session_authenticated and portal_client.is_logged_in(),
        session_token_present=portal_client.is_logged_in(),
        portal_url=portal_client.base_url,
        account_email=portal_client.username,
    )


# -----------------------------------------------------------------------------
# Meters Endpoints
# -----------------------------------------------------------------------------

@app.get(
    "/api/v1/meters",
    response_model=PaginatedResponse[MeterSummary],
    summary="List and Filter Smart Meters",
    tags=["Meters"],
    description=(
        "Retrieve a paginated list of smart meters with optional multi-attribute filtering, "
        "full-text search, and geographic proximity queries (Haversine formula)."
    ),
)
def list_meters(
    q: Optional[str] = Query(None, description="Search query by Meter ID or Serial Number"),
    make: Optional[str] = Query(None, description="Filter by manufacturer (HPL, Genus, L&T, Secure, Allied)"),
    phase_type: Optional[str] = Query(None, description="Filter by phase configuration ('single' or 'three')"),
    install_status: Optional[str] = Query(None, description="Filter by operational status ('Installed', 'Faulty', 'Decommissioned')"),
    dt_code: Optional[str] = Query(None, description="Filter by Distribution Transformer code (e.g. DT-001)"),
    feeder_code: Optional[str] = Query(None, description="Filter by parent feeder code (e.g. F-001)"),
    substation_code: Optional[str] = Query(None, description="Filter by substation code (e.g. SS-01)"),
    division_code: Optional[str] = Query(None, description="Filter by division code (e.g. D-01)"),
    circle_code: Optional[str] = Query(None, description="Filter by circle code (e.g. C-01)"),
    zone_code: Optional[str] = Query(None, description="Filter by zone code (e.g. Z-01)"),
    build: Optional[str] = Query(None, description="Filter by hardware build ('legacy' or 'v2')"),
    near_lat: Optional[float] = Query(None, description="Latitude for spatial proximity search"),
    near_lng: Optional[float] = Query(None, description="Longitude for spatial proximity search"),
    radius_km: Optional[float] = Query(None, description="Radius in kilometers for proximity search (requires near_lat & near_lng)"),
    sort_by: str = Query("meter_id", description="Field to sort by (meter_id, serial_number, make, dt_code, install_status, distance)"),
    sort_order: str = Query("asc", description="Sort direction ('asc' or 'desc')"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=500, description="Number of records per page"),
):
    try:
        return data_store.query_meters(
            q=q,
            make=make,
            phase_type=phase_type,
            install_status=install_status,
            dt_code=dt_code,
            feeder_code=feeder_code,
            substation_code=substation_code,
            division_code=division_code,
            circle_code=circle_code,
            zone_code=zone_code,
            build=build,
            near_lat=near_lat,
            near_lng=near_lng,
            radius_km=radius_km,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Error querying meters: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/meters/{meter_id}",
    response_model=MeterDetail,
    summary="Get Smart Meter Details",
    tags=["Meters"],
    description="Retrieve comprehensive details for a specific smart meter, including nameplate specifications, GPS coordinates, and reconciled 7-tier distribution hierarchy.",
)
def get_meter_details(meter_id: str):
    meter = data_store.get_meter(meter_id)
    if not meter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meter '{meter_id}' not found in Urja Meter Ops."
        )
    return meter


@app.get(
    "/api/v1/meters/{meter_id}/consumption",
    response_model=MeterConsumptionResponse,
    summary="Get Meter Consumption History",
    tags=["Meters"],
    description="Retrieve chronological 30-minute interval readings (kWh, kVAh, voltage) along with aggregate consumption analytics.",
)
def get_meter_consumption(meter_id: str):
    try:
        return portal_client.get_meter_energy(meter_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consumption data for meter '{meter_id}' not found."
        )
    except Exception as e:
        logger.error(f"Error fetching consumption for {meter_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/meters/{meter_id}/geo",
    response_model=dict,
    summary="Get Meter Geographic Coordinates",
    tags=["Meters"],
    description="Retrieve normalized GPS coordinates as numeric floats and in standard GeoJSON Point format.",
)
def get_meter_geo(meter_id: str):
    geo = portal_client.get_meter_geo(meter_id)
    if not geo:
        # Fallback to local store
        meter = data_store.get_meter(meter_id)
        if meter and meter.geo:
            geo = {"latitude": meter.geo.latitude, "longitude": meter.geo.longitude}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Geographic coordinates for meter '{meter_id}' not found."
            )
    return {
        "meter_id": meter_id,
        "latitude": geo["latitude"],
        "longitude": geo["longitude"],
        "geojson": {
            "type": "Point",
            "coordinates": [geo["longitude"], geo["latitude"]],
        }
    }


@app.get(
    "/api/v1/meters/{meter_id}/raw",
    summary="Raw Scraped Meter Data (Fallback Demo)",
    tags=["Meters"],
    description="Inspect raw parsed data obtained from the BeautifulSoup4 HTML fallback scraper for /meters/{id}.",
)
def get_meter_raw_scrape(meter_id: str):
    try:
        return portal_client.scrape_meter_page_html(meter_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meter '{meter_id}' not found on portal page."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Transformers Endpoints
# -----------------------------------------------------------------------------

@app.get(
    "/api/v1/transformers",
    response_model=PaginatedResponse[TransformerSummary],
    summary="List Distribution Transformers",
    tags=["Transformers"],
    description="Retrieve all distribution transformers (DTs) with rated capacity and connected meter counts.",
)
def list_transformers(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    try:
        return data_store.get_transformers(page=page, page_size=page_size)
    except Exception as e:
        logger.error(f"Error fetching transformers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/transformers/{code}",
    response_model=TransformerDetail,
    summary="Get Distribution Transformer Details",
    tags=["Transformers"],
    description="Get transformer details including rated kVA capacity and the full list of attached smart meters with health breakdown.",
)
def get_transformer(code: str):
    dt = data_store.get_transformer_detail(code)
    if not dt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Distribution transformer '{code}' not found."
        )
    return dt


# -----------------------------------------------------------------------------
# Hierarchy Endpoints
# -----------------------------------------------------------------------------

@app.get(
    "/api/v1/hierarchy",
    response_model=list[HierarchyTreeNode],
    summary="Reconstructed Network Hierarchy Tree",
    tags=["Hierarchy"],
    description=(
        "Reconstruct the full 7-tier distribution network hierarchy: "
        "Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> Distribution Transformer. "
        "Automatically heals incomplete and missing codes/names in legacy records."
    ),
)
def get_hierarchy(
    root_level: Optional[str] = Query(None, description="Optional root level filter ('zone', 'circle', 'division', 'subdivision', 'substation', 'feeder', 'dt')"),
    root_code: Optional[str] = Query(None, description="Optional root code filter (e.g. 'Z-01', 'C-01', 'DT-001')"),
):
    try:
        data_store.ensure_synced()
        tree = data_store.hierarchy_engine.build_tree(
            data_store._raw_meters,
            root_level=root_level,
            root_code=root_code,
        )
        return tree
    except Exception as e:
        logger.error(f"Error building hierarchy tree: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Analytics, Bulk Export & Cache Management
# -----------------------------------------------------------------------------

@app.get(
    "/api/v1/analytics/summary",
    response_model=AnalyticsSummary,
    summary="Fleet Overview and Grid Analytics",
    tags=["Analytics"],
    description="High-level operational metrics: status distribution, manufacturers, phase types, transformer capacities, and healed anomaly metrics.",
)
def get_analytics_summary():
    try:
        return data_store.get_analytics_summary()
    except Exception as e:
        logger.error(f"Error computing analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/export",
    summary="Bulk Meter Dataset Export",
    tags=["Export"],
    description="Export complete dataset of all 403 smart meters obtained via the HMAC-SHA256 signed portal endpoint.",
)
def get_export_dataset():
    data_store.ensure_synced()
    return {
        "total": len(data_store._raw_meters),
        "data": data_store._raw_meters,
        "last_synced_at": data_store.get_analytics_summary().last_synced_at,
    }


@app.post(
    "/api/v1/cache/refresh",
    summary="Force Refresh Cached Portal Data",
    tags=["System"],
    description="Trigger an immediate re-sync of all smart meters and transformers from the legacy portal.",
)
def refresh_cache():
    try:
        data_store.ensure_synced(force=True)
        return {
            "status": "success",
            "message": "Dataset successfully re-synchronized from Urja portal.",
            "total_meters": len(data_store._raw_meters),
            "total_transformers": len(data_store._raw_dts),
            "healed_anomalies": data_store.hierarchy_engine.healed_count,
        }
    except Exception as e:
        logger.error(f"Cache refresh failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh cache: {e}")
