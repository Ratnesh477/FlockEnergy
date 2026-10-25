# Engineering Reflection (REFLECTION.md)

**Project:** Flock Energy — Urja Meter Ops REST API Service  
**Date:** October 2026  

---

### 1. What assumptions did you make?

1. **Read-Only Upstream & Single Discom Jurisdiction:**  
   We assumed the Urja Meter Ops portal is exclusively a read-only telemetry and operational system for Jaipur (Rajasthan, India). Because all geographic coordinates were clustered around Jaipur (~26.85°N to 26.94°N, 75.72°E to 75.83°E) and meter timestamps had no explicit offset, we assumed Indian Standard Time (`UTC+05:30`) as the canonical timezone when converting `DD/MM/YYYY HH:mm` into ISO 8601 strings.

2. **Dataset Volatility & Staleness (TTL = 15 minutes):**  
   Because smart meter interval telemetry arrives at 30-minute intervals and physical grid topology (substations, feeders, distribution transformers) changes infrequently, we assumed that caching the 403-meter dataset for 15 minutes provides an optimal balance between low upstream load and data freshness. We also assumed downstream consumers would occasionally need on-demand sync, which we provided via `POST /api/v1/cache/refresh`.

3. **Topology Determinism Across Inconsistent Nodes:**  
   When encountering the 22 records with missing names or codes in the hierarchy (e.g. `Circle 6` with empty code, or `C-01` with empty name), we assumed the network hierarchy is deterministic and closed: if 95% of meters connected to DT-001 or Feeder 1 exhibit a specific parent code, incomplete sister nodes can be safely repaired using the canonical code-name dictionary built across the complete fleet.

---

### 2. Which part was the most difficult, and how did you get unstuck?

The most difficult part was the initial authentication and discovering how SvelteKit handled form submissions and bulk exports:

1. **SvelteKit CSRF Rejection:**  
   When attempting the first login via `curl` and Python `httpx`, the server immediately returned `403 Forbidden: Cross-site POST form submissions are forbidden`. We inspected the SvelteKit documentation and observed that SvelteKit inspects the `Origin` and `Referer` headers for any non-GET request. By mimicking a legitimate browser session with `Origin: https://urja-ops.flockenergy.tech` and `Referer: https://urja-ops.flockenergy.tech/login`, the request succeeded with `{"type":"redirect","status":303,"location":"/meters"}` and established the `__Secure-better-auth.session_token` cookie.

2. **Cracking the Cryptographic Export Protocol:**  
   While inspecting the Transformers page bundle (`nodes/4.2Bgc2kUI.js`), we discovered that clicking the "Export all meters" button executed an asynchronous Web Crypto HMAC signing routine calling `/portal/keys` and `/portal/export`. By decompiling the JavaScript, we extracted the exact canonical payload format:
   ```
   GET\n/portal/export\npage=1\n<timestamp>
   ```
   Replicating this signing algorithm in Python with `hmac.new(secret, msg, hashlib.sha256)` unlocked the entire 403-meter dataset in a single call, eliminating the need to scrape 403 separate HTML pages.

---

### 3. If you had another day, what would you improve?

1. **Persistent SQLite / PostgreSQL + PostGIS Storage Layer:**  
   Currently, the service maintains the 403 meters in an in-memory datastore with a 15-minute TTL. While lightning fast (sub-millisecond queries) for 400 meters, if the utility expands to 500,000 smart meters across Rajasthan, holding raw objects in Python RAM would cause memory bloat. Replacing the in-memory store with an embedded SQLite database or PostgreSQL with PostGIS would enable indexed spatial bounding-box queries (`ST_DWithin`), full-text search, and relational foreign keys.

2. **Background Async Polling & Change-Data-Capture (CDC):**  
   Implement an asynchronous background worker (using Celery or an `asyncio` task loop) that polls `/portal/export` periodically and emits webhook events (e.g. `meter.status_changed`, `meter.anomaly_detected`, `meter.voltage_drop`) whenever a meter transitions from `Installed` to `Faulty`.

3. **Batch Consumption Pre-fetching & Time-Series Caching:**  
   Currently, consumption readings are fetched on-demand per meter (`GET /api/v1/meters/{id}/consumption`). For data science teams running grid load analysis, batch pre-fetching into an in-memory DuckDB or Parquet file would allow instant multi-meter aggregate queries (e.g., "Total kWh consumed across all meters on Feeder 1 during peak hours").

---

### 4. What mistake did you make while solving this?

When first inspecting the meter details page on `/meters/[id]`, we noticed that calling `/portal/meters/J100000` returned a `404 Not Found`. We initially assumed there was no JSON API for meter details and wrote a BeautifulSoup4 HTML scraper to parse the `<dl>` nameplate list and `<nav>` breadcrumbs.

While the BeautifulSoup4 scraper worked, we subsequently noticed that some meters displayed `Serial No` while others displayed `SerialNo`, and some had `Phase Type` while others had `PhaseType`. Only after digging deeper into the client JS bundle did we realize that 165 meters were `v2` builds with JSON stored inside a stringified `classData` field, whereas 238 were `legacy` builds with `parameterName`/`parameterValue` tuples!

Had we decompiled the bundle earlier before writing the initial regex scraper, we would have seen the legacy author's own decoding function `R(e)` right away. However, writing the HTML scraper first ended up being a blessing in disguise: it gave us a fully functional fallback scraper that makes the client resilient even if the internal export endpoint is ever altered or restricted.

---

### 5. If you were reviewing your own submission, what would you criticise?

1. **In-Memory Query Scaling Ceiling:**  
   The in-memory spatial search uses a linear $O(N)$ scan using the Haversine formula across all meters. For $N = 403$, the query executes in less than 0.5 milliseconds, which is exceptionally fast. However, for $N = 1,000,000$, a linear scan in Python would degrade query response time to several seconds. A production implementation should use an R-Tree index (such as `scipy.spatial.cKDTree` or PostGIS R-tree) for sub-millisecond spatial lookups at scale.

2. **Single Global Portal Session:**  
   The current adapter uses a single shared authenticated session. If multiple downstream clients make concurrent requests that trigger re-authentication simultaneously, a brief lock contention occurs. A session pool or token-bucket rate limiter would improve concurrency under extreme multi-tenant load.

3. **Mocking External Portal in CI/CD:**  
   The test suite currently includes tests that interact with the live portal (which validates end-to-end correctness). In a production continuous integration pipeline with flaky internet access or upstream maintenance windows, having recorded VCR.py fixtures would guarantee deterministic offline test runs.
