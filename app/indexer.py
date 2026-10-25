import math
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.client import UrjaPortalClient, portal_client
from app.config import settings
from app.hierarchy import HierarchyEngine
from app.models import (
    AnalyticsSummary,
    GeoLocation,
    MeterDetail,
    MeterSummary,
    PaginatedResponse,
    TransformerDetail,
    TransformerSummary,
)

logger = logging.getLogger(__name__)


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on Earth in kilometers."""
    r = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


class LocalDataStore:
    """
    In-memory spatial index, attribute query engine, and caching layer.
    
    Provides high-performance filtering, proximity search, hierarchy reconstruction,
    and bulk analytics that the legacy Urja portal cannot perform natively.
    """

    def __init__(self, client: Optional[UrjaPortalClient] = None, ttl_seconds: Optional[int] = None):
        self.client = client or portal_client
        self.ttl_seconds = ttl_seconds or settings.cache_ttl_seconds
        self.hierarchy_engine = HierarchyEngine()
        
        self._lock = threading.RLock()
        self._raw_meters: list[dict[str, Any]] = []
        self._meter_map: dict[str, dict[str, Any]] = {}
        self._raw_dts: list[dict[str, Any]] = []
        self._dt_map: dict[str, dict[str, Any]] = {}
        self._last_synced_at: Optional[float] = None
        self._sync_in_progress = False

    def is_stale(self) -> bool:
        """Check if cached data is absent or older than the configured TTL."""
        if not self._last_synced_at or not self._raw_meters:
            return True
        return (time.time() - self._last_synced_at) > self.ttl_seconds

    def ensure_synced(self, force: bool = False) -> None:
        """Ensure local dataset is synchronized from portal."""
        if not force and not self.is_stale():
            return

        with self._lock:
            # Recheck inside lock
            if not force and not self.is_stale():
                return

            logger.info("Synchronizing complete dataset from Urja portal...")
            # 1. Fetch all meters via signed bulk export
            export_resp = self.client.export_all_meters()
            meters = export_resp.get("data") or []

            # 2. Fetch all distribution transformers
            # DTs endpoint is paginated (40 DTs total, 20 per page)
            all_dts = []
            page = 1
            while True:
                dt_resp = self.client.get_distribution_transformers(page=page)
                dt_data = dt_resp.get("data") or []
                all_dts.extend(dt_data)
                total = dt_resp.get("total", len(all_dts))
                if len(all_dts) >= total or not dt_data:
                    break
                page += 1

            # 3. Index hierarchy and learn canonical nodes
            self.hierarchy_engine.build_indexes(meters)

            # 4. Update in-memory collections
            self._raw_meters = meters
            self._meter_map = {m["meterId"]: m for m in meters}
            self._raw_dts = all_dts
            self._dt_map = {dt["code"]: dt for dt in all_dts}
            self._last_synced_at = time.time()
            logger.info(
                f"Sync complete. Indexed {len(self._raw_meters)} meters, "
                f"{len(self._raw_dts)} transformers. "
                f"Repaired {self.hierarchy_engine.healed_count} hierarchy anomalies."
            )

    def get_meter(self, meter_id: str) -> Optional[MeterDetail]:
        """Fetch detailed meter model by ID, with healed hierarchy and coordinates."""
        self.ensure_synced()
        raw = self._meter_map.get(meter_id)
        if not raw:
            # Fallback attempt via HTML scraper if not in bulk cache
            try:
                scraped = self.client.scrape_meter_page_html(meter_id)
                geo = self.client.get_meter_geo(meter_id)
                geo_model = GeoLocation(latitude=geo["latitude"], longitude=geo["longitude"]) if geo else None
                return MeterDetail(
                    meter_id=scraped["meter_id"],
                    serial_number=scraped["serial_number"],
                    make=scraped["make"],
                    phase_type=scraped["phase_type"],
                    install_status=scraped["install_status"],
                    install_type=scraped["install_type"],
                    dt_code=scraped.get("dtCode", "N/A"),
                    geo=geo_model,
                    nameplate=scraped.get("nameplate"),
                )
            except Exception:
                return None

        # Build clean typed MeterDetail from cached bulk data
        h = raw.get("hierarchy") or {}
        norm_h, _ = self.hierarchy_engine.heal_and_normalize(h, meter_id)
        
        geo_dict = raw.get("geo") or {}
        geo_model = None
        if "lat" in geo_dict and "lng" in geo_dict and geo_dict["lat"] is not None:
            geo_model = GeoLocation(
                latitude=float(geo_dict["lat"]),
                longitude=float(geo_dict["lng"])
            )

        nameplate = {
            "Meter ID": raw.get("meterId", ""),
            "Serial No": raw.get("serialNo", ""),
            "Make": raw.get("make", ""),
            "Phase Type": raw.get("phaseType", ""),
            "Installation Status": raw.get("installStatus", ""),
            "Installation Type": raw.get("installType", ""),
            "DT Code": raw.get("dtCode", ""),
            "Build Generation": raw.get("build", ""),
        }

        return MeterDetail(
            meter_id=raw["meterId"],
            serial_number=raw.get("serialNo", ""),
            make=raw.get("make", ""),
            phase_type=raw.get("phaseType", "single"),
            install_status=raw.get("installStatus", "Installed"),
            install_type=raw.get("installType"),
            dt_code=raw.get("dtCode", ""),
            build=raw.get("build"),
            geo=geo_model,
            hierarchy=norm_h,
            nameplate=nameplate,
        )

    def query_meters(
        self,
        q: Optional[str] = None,
        make: Optional[str] = None,
        phase_type: Optional[str] = None,
        install_status: Optional[str] = None,
        dt_code: Optional[str] = None,
        feeder_code: Optional[str] = None,
        substation_code: Optional[str] = None,
        division_code: Optional[str] = None,
        circle_code: Optional[str] = None,
        zone_code: Optional[str] = None,
        build: Optional[str] = None,
        near_lat: Optional[float] = None,
        near_lng: Optional[float] = None,
        radius_km: Optional[float] = None,
        sort_by: str = "meter_id",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse[MeterSummary]:
        """
        Execute an advanced query against smart meters with attribute filters,
        text search, and geographic proximity filtering.
        """
        self.ensure_synced()

        filtered = []
        for m in self._raw_meters:
            # 1. Text search (ID or Serial)
            if q:
                q_lower = q.lower().strip()
                m_id = m.get("meterId", "").lower()
                m_ser = m.get("serialNo", "").lower()
                if q_lower not in m_id and q_lower not in m_ser:
                    continue

            # 2. Attribute filters
            if make and m.get("make", "").lower() != make.lower():
                continue
            if phase_type and m.get("phaseType", "").lower() != phase_type.lower():
                continue
            if install_status and m.get("installStatus", "").lower() != install_status.lower():
                continue
            if dt_code and m.get("dtCode", "").lower() != dt_code.lower():
                continue
            if build and m.get("build", "").lower() != build.lower():
                continue

            # 3. Hierarchy filters
            h = m.get("hierarchy") or {}
            if feeder_code and (h.get("feeder", {}).get("code", "").lower() != feeder_code.lower()):
                continue
            if substation_code and (h.get("substation", {}).get("code", "").lower() != substation_code.lower()):
                continue
            if division_code and (h.get("division", {}).get("code", "").lower() != division_code.lower()):
                continue
            if circle_code and (h.get("circle", {}).get("code", "").lower() != circle_code.lower()):
                continue
            if zone_code and (h.get("zone", {}).get("code", "").lower() != zone_code.lower()):
                continue

            # 4. Spatial proximity filter
            dist = None
            if near_lat is not None and near_lng is not None:
                geo = m.get("geo") or {}
                m_lat = geo.get("lat")
                m_lng = geo.get("lng")
                if m_lat is None or m_lng is None:
                    continue
                dist = haversine_distance_km(near_lat, near_lng, float(m_lat), float(m_lng))
                if radius_km is not None and dist > radius_km:
                    continue

            filtered.append((m, dist))

        # Sorting
        reverse = (sort_order.lower() == "desc")
        if near_lat is not None and near_lng is not None and sort_by in ("distance", "distance_km"):
            filtered.sort(key=lambda x: x[1] if x[1] is not None else float("inf"), reverse=reverse)
        elif sort_by == "serial_number":
            filtered.sort(key=lambda x: x[0].get("serialNo", ""), reverse=reverse)
        elif sort_by == "make":
            filtered.sort(key=lambda x: x[0].get("make", ""), reverse=reverse)
        elif sort_by == "dt_code":
            filtered.sort(key=lambda x: x[0].get("dtCode", ""), reverse=reverse)
        elif sort_by == "install_status":
            filtered.sort(key=lambda x: x[0].get("installStatus", ""), reverse=reverse)
        else:
            # Default sort by meter_id
            filtered.sort(key=lambda x: x[0].get("meterId", ""), reverse=reverse)

        total = len(filtered)
        total_pages = max(1, math.ceil(total / page_size)) if page_size > 0 else 1
        page = max(1, min(page, total_pages)) if total > 0 else 1

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_items = filtered[start_idx:end_idx]

        summaries = [
            MeterSummary(
                meter_id=item[0]["meterId"],
                serial_number=item[0].get("serialNo", ""),
                make=item[0].get("make", ""),
                phase_type=item[0].get("phaseType", "single"),
                install_status=item[0].get("installStatus", "Installed"),
                dt_code=item[0].get("dtCode", ""),
                build=item[0].get("build"),
            )
            for item in paged_items
        ]

        return PaginatedResponse[MeterSummary](
            data=summaries,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_transformers(self, page: int = 1, page_size: int = 20) -> PaginatedResponse[TransformerSummary]:
        """Fetch paginated distribution transformers list with attached meter counts."""
        self.ensure_synced()

        # Count meters per DT
        dt_counts: dict[str, int] = {}
        for m in self._raw_meters:
            code = m.get("dtCode", "")
            if code:
                dt_counts[code] = dt_counts.get(code, 0) + 1

        items = []
        for dt in self._raw_dts:
            code = dt.get("code", "")
            items.append(
                TransformerSummary(
                    code=code,
                    name=dt.get("name", ""),
                    feeder_code=dt.get("feederCode", ""),
                    capacity_kva=float(dt.get("capacityKva", 0.0)),
                    meter_count=dt_counts.get(code, 0),
                )
            )

        items.sort(key=lambda x: x.code)
        total = len(items)
        total_pages = max(1, math.ceil(total / page_size))
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        return PaginatedResponse[TransformerSummary](
            data=items[start_idx:end_idx],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_transformer_detail(self, dt_code: str) -> Optional[TransformerDetail]:
        """Fetch detailed transformer info including its connected meters and health status."""
        self.ensure_synced()
        raw_dt = self._dt_map.get(dt_code.upper())
        if not raw_dt:
            # Check case-insensitive
            for k, v in self._dt_map.items():
                if k.lower() == dt_code.lower():
                    raw_dt = v
                    break
        if not raw_dt:
            return None

        # Find connected meters
        meters = []
        installed_count = 0
        faulty_count = 0
        decommissioned_count = 0

        for m in self._raw_meters:
            if m.get("dtCode", "").lower() == dt_code.lower():
                status = m.get("installStatus", "Installed")
                if status == "Installed":
                    installed_count += 1
                elif status == "Faulty":
                    faulty_count += 1
                elif status == "Decommissioned":
                    decommissioned_count += 1

                meters.append(
                    MeterSummary(
                        meter_id=m["meterId"],
                        serial_number=m.get("serialNo", ""),
                        make=m.get("make", ""),
                        phase_type=m.get("phaseType", "single"),
                        install_status=status,
                        dt_code=m.get("dtCode", ""),
                        build=m.get("build"),
                    )
                )

        meters.sort(key=lambda x: x.meter_id)

        return TransformerDetail(
            code=raw_dt.get("code", dt_code),
            name=raw_dt.get("name", ""),
            feeder_code=raw_dt.get("feederCode", ""),
            capacity_kva=float(raw_dt.get("capacityKva", 0.0)),
            meter_count=len(meters),
            installed_count=installed_count,
            faulty_count=faulty_count,
            decommissioned_count=decommissioned_count,
            meters=meters,
        )

    def get_analytics_summary(self) -> AnalyticsSummary:
        """Calculate system-wide statistics, health distribution, and grid metrics."""
        self.ensure_synced()

        by_status: dict[str, int] = {}
        by_make: dict[str, int] = {}
        by_phase: dict[str, int] = {}
        by_build: dict[str, int] = {}

        for m in self._raw_meters:
            status = m.get("installStatus", "Unknown")
            by_status[status] = by_status.get(status, 0) + 1

            make = m.get("make", "Unknown")
            by_make[make] = by_make.get(make, 0) + 1

            phase = m.get("phaseType", "Unknown")
            by_phase[phase] = by_phase.get(phase, 0) + 1

            build = m.get("build", "Unknown")
            by_build[build] = by_build.get(build, 0) + 1

        total_cap = sum(float(dt.get("capacityKva", 0.0)) for dt in self._raw_dts)
        synced_iso = (
            datetime.fromtimestamp(self._last_synced_at, tz=timezone.utc).isoformat()
            if self._last_synced_at
            else datetime.now(timezone.utc).isoformat()
        )

        return AnalyticsSummary(
            total_meters=len(self._raw_meters),
            by_status=by_status,
            by_make=by_make,
            by_phase=by_phase,
            by_build=by_build,
            total_transformers=len(self._raw_dts),
            total_transformer_capacity_kva=round(total_cap, 1),
            healed_hierarchy_anomalies=self.hierarchy_engine.healed_count,
            last_synced_at=synced_iso,
        )


# Global shared data store instance
data_store = LocalDataStore()
