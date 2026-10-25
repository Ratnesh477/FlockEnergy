import hashlib
import hmac
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import httpx
from bs4 import BeautifulSoup

from app.config import settings

logger = logging.getLogger(__name__)

# Jaipur, Rajasthan is in Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30))


class UrjaPortalClient:
    """
    HTTP Adapter and Reverse-Engineered Client for the Urja Meter Ops legacy portal.
    
    Handles:
    - Session lifecycle, cookie persistence, and CSRF protection (Better-Auth)
    - Transparent re-authentication upon session expiry
    - Internal JSON API calls (/portal/meters/search, /portal/dts, etc.)
    - HMAC-SHA256 signed requests for bulk export (/portal/export)
    - Resilient HTML fallback scraping via BeautifulSoup4 (/meters/{id})
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.portal_base_url).rstrip("/")
        self.username = username or settings.portal_username
        self.password = password or settings.portal_password
        self.timeout = timeout or settings.request_timeout_seconds
        
        # HTTP client with persistent cookie jar
        self.client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            headers={
                "User-Agent": "FlockEnergy-UrjaAPI/1.0 (Integration Client)",
                "Accept": "application/json, text/html, */*",
            }
        )
        self._lock = threading.RLock()
        self._session_authenticated = False
        self._cached_signing_secret: Optional[str] = None
        self._secret_cached_at: float = 0.0

    def is_logged_in(self) -> bool:
        """Check if session cookie exists in cookie jar."""
        for cookie in self.client.cookies.jar:
            if cookie.name == "__Secure-better-auth.session_token":
                return True
        return False

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Authenticate against Urja Meter Ops portal using Better-Auth form POST.
        Requires Origin and Referer headers to satisfy SvelteKit CSRF policy.
        """
        user = username or self.username
        pwd = password or self.password
        
        login_url = f"{self.base_url}/login"
        headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/login",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {
            "email": user,
            "password": pwd,
        }

        with self._lock:
            try:
                response = self.client.post(login_url, data=payload, headers=headers)
                
                # Check for session token cookie
                has_cookie = any(
                    c.name == "__Secure-better-auth.session_token" 
                    for c in self.client.cookies.jar
                )

                if (response.status_code in (200, 302, 303)) and has_cookie:
                    self._session_authenticated = True
                    logger.info("Successfully authenticated with Urja portal.")
                    return True
                
                logger.warning(
                    f"Login failed: status={response.status_code}, response={response.text[:200]}"
                )
                self._session_authenticated = False
                return False

            except httpx.HTTPError as exc:
                logger.error(f"Network error during portal authentication: {exc}")
                self._session_authenticated = False
                raise

    def _ensure_authenticated(self) -> None:
        """Verify session is active or perform automatic login."""
        if not self.is_logged_in() or not self._session_authenticated:
            success = self.login()
            if not success:
                raise PermissionError("Failed to authenticate with legacy Urja portal.")

    def _request_with_retry(
        self,
        method: str,
        path: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Any] = None,
        retry_on_auth_failure: bool = True,
    ) -> httpx.Response:
        """
        Make an HTTP request to the legacy portal with automatic re-authentication 
        and retry if the session has expired (401 or 302 to /login).
        """
        self._ensure_authenticated()
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        req_headers = headers.copy() if headers else {}

        response = self.client.request(
            method=method,
            url=url,
            headers=req_headers,
            params=params,
            data=data,
            json=json_data,
        )

        # Detect session expiry:
        # Case A: 401 Unauthorized with {"error":"unauthorized"}
        # Case B: 302 Found redirecting to /login
        is_unauthorized = (response.status_code == 401)
        is_redirect_to_login = (
            response.status_code in (302, 303, 307) and 
            "/login" in response.headers.get("location", "")
        )

        if (is_unauthorized or is_redirect_to_login) and retry_on_auth_failure:
            logger.warning(f"Session expired while requesting {path} (status={response.status_code}). Re-authenticating...")
            with self._lock:
                self.login()
            # Retry request with new session cookie
            response = self.client.request(
                method=method,
                url=url,
                headers=req_headers,
                params=params,
                data=data,
                json=json_data,
            )

        return response

    # -------------------------------------------------------------------------
    # Core API Endpoints
    # -------------------------------------------------------------------------

    def search_meters(self, q: str = "", page: int = 1) -> dict[str, Any]:
        """
        Search smart meters via legacy internal endpoint:
        GET /portal/meters/search?q={q}&page={page}
        """
        params = {"q": q, "page": page}
        resp = self._request_with_retry("GET", "/portal/meters/search", params=params)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to search meters: {resp.status_code}",
                request=resp.request,
                response=resp
            )
        return resp.json()

    def get_meter_geo(self, meter_id: str) -> Optional[dict[str, float]]:
        """
        Fetch meter GPS coordinates via /portal/meters/{id}/geo.
        Normalizes string latitude and longitude to floats.
        """
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/geo")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to fetch meter geo for {meter_id}: {resp.status_code}",
                request=resp.request,
                response=resp
            )
        payload = resp.json().get("data") or {}
        try:
            return {
                "latitude": float(payload["latitude"]),
                "longitude": float(payload["longitude"]),
            }
        except (KeyError, ValueError, TypeError):
            return None

    def get_meter_energy(self, meter_id: str) -> dict[str, Any]:
        """
        Fetch 30-minute interval smart meter readings via /portal/meters/{id}/energy.
        Normalizes:
        - Timestamps from 'DD/MM/YYYY HH:mm' into ISO 8601 strings
        - 'kwh', 'kvah', 'voltR' strings into floats
        - Computes statistical summary (reading count, energy consumed, voltage metrics)
        """
        resp = self._request_with_retry("GET", f"/portal/meters/{meter_id}/energy")
        if resp.status_code == 404:
            raise KeyError(f"Meter '{meter_id}' not found.")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to fetch meter energy for {meter_id}: {resp.status_code}",
                request=resp.request,
                response=resp
            )

        raw_readings = resp.json().get("data") or []
        normalized_readings = []
        voltages = []

        for item in raw_readings:
            raw_ts = item.get("timestamp", "")
            iso_ts = self._parse_legacy_timestamp(raw_ts)

            try:
                kwh = float(item.get("kwh", 0.0) or 0.0)
            except (ValueError, TypeError):
                kwh = 0.0

            try:
                kvah = float(item.get("kvah", 0.0) or 0.0)
            except (ValueError, TypeError):
                kvah = 0.0

            try:
                volt_r = float(item.get("voltR", 0.0) or 0.0)
            except (ValueError, TypeError):
                volt_r = 0.0

            normalized_readings.append({
                "timestamp": iso_ts,
                "raw_timestamp": raw_ts,
                "kwh": round(kwh, 2),
                "kvah": round(kvah, 2),
                "volt_r": round(volt_r, 1),
            })
            if volt_r > 0:
                voltages.append(volt_r)

        # Calculate statistics
        reading_count = len(normalized_readings)
        if reading_count > 0:
            start_time = normalized_readings[0]["timestamp"]
            end_time = normalized_readings[-1]["timestamp"]
            kwh_initial = normalized_readings[0]["kwh"]
            kwh_latest = normalized_readings[-1]["kwh"]
            kwh_total_consumed = round(max(0.0, kwh_latest - kwh_initial), 2)
            avg_v = round(sum(voltages) / len(voltages), 1) if voltages else 0.0
            min_v = min(voltages) if voltages else 0.0
            max_v = max(voltages) if voltages else 0.0
        else:
            start_time = None
            end_time = None
            kwh_initial = 0.0
            kwh_latest = 0.0
            kwh_total_consumed = 0.0
            avg_v = 0.0
            min_v = 0.0
            max_v = 0.0

        stats = {
            "reading_count": reading_count,
            "start_time": start_time,
            "end_time": end_time,
            "kwh_initial": kwh_initial,
            "kwh_latest": kwh_latest,
            "kwh_total_consumed": kwh_total_consumed,
            "avg_voltage": avg_v,
            "min_voltage": min_v,
            "max_voltage": max_v,
        }

        return {
            "meter_id": meter_id,
            "readings": normalized_readings,
            "stats": stats,
        }

    def get_distribution_transformers(self, page: int = 1) -> dict[str, Any]:
        """
        Fetch distribution transformers (DTs) via /portal/dts?page={page}.
        """
        resp = self._request_with_retry("GET", f"/portal/dts?page={page}")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to fetch transformers: {resp.status_code}",
                request=resp.request,
                response=resp
            )
        return resp.json()

    def get_signing_secret(self, force_refresh: bool = False) -> str:
        """
        Fetch HMAC-SHA256 signing secret via /portal/keys.
        Caches secret in memory for 10 minutes.
        """
        now = time.time()
        if not force_refresh and self._cached_signing_secret and (now - self._secret_cached_at < 600):
            return self._cached_signing_secret

        resp = self._request_with_retry("GET", "/portal/keys")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to fetch portal keys: {resp.status_code}",
                request=resp.request,
                response=resp
            )
        secret = resp.json()["data"]["signingSecret"]
        self._cached_signing_secret = secret
        self._secret_cached_at = now
        return secret

    def export_all_meters(self) -> dict[str, Any]:
        """
        Fetch the complete bulk dataset of all smart meters via HMAC-SHA256 signed endpoint:
        GET /portal/export?page=1
        
        Headers required:
        - x-timestamp: Unix epoch string (e.g. "1740000000")
        - x-signature: HMAC-SHA256 hex digest of "GET\n/portal/export\npage=1\n<timestamp>"
        """
        secret = self.get_signing_secret()
        timestamp = str(int(time.time()))
        path = "/portal/export"
        query = "page=1"
        message = f"GET\n{path}\n{query}\n{timestamp}".encode("utf-8")

        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

        headers = {
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

        resp = self._request_with_retry("GET", f"{path}?{query}", headers=headers)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to export bulk meters: {resp.status_code}",
                request=resp.request,
                response=resp
            )
        return resp.json()

    # -------------------------------------------------------------------------
    # HTML Fallback Scraper (BeautifulSoup4)
    # -------------------------------------------------------------------------

    def scrape_meter_page_html(self, meter_id: str) -> dict[str, Any]:
        """
        Direct HTML parser fallback for /meters/{id}.
        Extracts Nameplate definition list (<dl>), breadcrumb navigation (<nav>),
        and parses both legacy parameter lists and v2 stringified classData.
        """
        resp = self._request_with_retry("GET", f"/meters/{meter_id}")
        if resp.status_code == 404:
            raise KeyError(f"Meter '{meter_id}' not found.")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError(
                f"Failed to scrape meter page {meter_id}: {resp.status_code}",
                request=resp.request,
                response=resp
            )

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 1. Parse Nameplate (<dl>)
        nameplate_dict: dict[str, str] = {}
        dl = soup.find("dl")
        if dl:
            for div in dl.find_all("div"):
                dt = div.find("dt")
                dd = div.find("dd")
                if dt and dd:
                    key = dt.get_text(strip=True)
                    val = dd.get_text(strip=True)
                    nameplate_dict[key] = val

        # 2. Parse Breadcrumbs Hierarchy (<nav>)
        breadcrumbs = []
        nav = soup.find("nav", class_=re.compile(r"flex.*text-xs"))
        if nav:
            for span in nav.find_all("span"):
                text = span.get_text(strip=True)
                if text and text != "›":
                    breadcrumbs.append(text)

        # 3. Also check embedded SvelteKit data for highest fidelity
        embedded_detail = {}
        embedded_hierarchy = {}
        match = re.search(r'detail:(\{.*?\})\s*,\s*hierarchy:(\{.*?\})', html)
        if match:
            try:
                # SvelteKit JS literal to JSON cleanup
                detail_str = match.group(1)
                hier_str = match.group(2)
                # Parse detail handling classData vs data
                if "classData" in detail_str:
                    cd_match = re.search(r'classData:\s*("(\\.|[^"\\])*")', detail_str)
                    if cd_match:
                        raw_json_str = json.loads(cd_match.group(1))
                        parsed_cd = json.loads(raw_json_str)
                        installed_m = parsed_cd.get("installed_meter", {})
                        embedded_detail = {k: str(v) for k, v in installed_m.items()}
            except Exception as e:
                logger.debug(f"Could not parse embedded script JSON: {e}")

        # Normalize key attributes
        serial = (
            nameplate_dict.get("Serial No") or 
            nameplate_dict.get("SerialNo") or 
            embedded_detail.get("SerialNo") or 
            "N/A"
        )
        make = (
            nameplate_dict.get("Make") or 
            embedded_detail.get("Make") or 
            "N/A"
        )
        phase = (
            nameplate_dict.get("Phase Type") or 
            nameplate_dict.get("PhaseType") or 
            embedded_detail.get("PhaseType") or 
            "single"
        )
        status = (
            nameplate_dict.get("Installation Status") or 
            nameplate_dict.get("InstallationStatus") or 
            embedded_detail.get("InstallationStatus") or 
            "Installed"
        )
        install_type = (
            nameplate_dict.get("Installation Type") or 
            nameplate_dict.get("InstallationType") or 
            embedded_detail.get("InstallationType") or 
            "Whole Current"
        )

        return {
            "meter_id": meter_id,
            "serial_number": serial,
            "make": make,
            "phase_type": phase.lower(),
            "install_status": status,
            "install_type": install_type,
            "nameplate": nameplate_dict,
            "breadcrumbs": breadcrumbs,
        }

    # -------------------------------------------------------------------------
    # Helper Utilities
    # -------------------------------------------------------------------------

    def _parse_legacy_timestamp(self, ts_str: str) -> str:
        """Parse 'DD/MM/YYYY HH:mm' into standard ISO 8601 string."""
        if not ts_str:
            return ""
        try:
            dt = datetime.strptime(ts_str.strip(), "%d/%m/%Y %H:%M")
            dt = dt.replace(tzinfo=IST)
            return dt.isoformat()
        except ValueError:
            return ts_str


# Global shared client instance
portal_client = UrjaPortalClient()
