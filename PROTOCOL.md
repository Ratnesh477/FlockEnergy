# Protocol Discovery & Reverse-Engineering Report (PROTOCOL.md)

**System Under Inspection:** Urja Meter Ops (`https://urja-ops.flockenergy.tech`)  
**Target Utility:** Electricity Distribution Utility (Jaipur Discom / Grid Operations)  
**Author:** Flock Energy API Integration Engineering  
**Date:** October 2026  

---

## 1. Executive Summary

The "Urja Meter Ops" portal is an internal operations web application built on **SvelteKit** (Vite frontend with server-side rendering and client-side hydration) backed by **Better-Auth** session management. While the portal outwardly presents itself as a human-facing web portal without published external API documentation, detailed network reconnaissance and JavaScript bundle disassembly revealed a hybrid architecture:

1. **Internal REST API (`/portal/*`)**: Clean JSON micro-endpoints called by SvelteKit client components.
2. **Bulk Export API (`/portal/export`)**: An HMAC-SHA256 cryptographically signed bulk data pipeline capable of streaming the entire 403-meter fleet and hierarchy in a single network round-trip.
3. **HTML / SSR Surface (`/meters/[id]`, `/transformers`)**: SvelteKit server routes returning server-rendered HTML containing nameplates and breadcrumbs with embedded devalue-serialized state.
4. **Data Polymorphism & Quirks**: The legacy dataset is divided into two distinct firmware generations (`legacy` vs `v2`) with differing data structures, stringified JSON blobs, and 22 records with incomplete hierarchy nodes.

---

## 2. Authentication & Session Architecture

### 2.1 Credentials
- **Default Operator Account:** `operator@urja.local`
- **Default Password:** `urja-ops-2026`

### 2.2 Authentication Flow
```
Client / Agent                     SvelteKit Server (/login)
      |                                        |
      |-- POST /login ------------------------>|
      |   (email, password, Origin, Referer)   |
      |                                        |
      |<-- 200 OK or 303 See Other ------------|
      |   Set-Cookie: __Secure-better-auth...  |
      |   {"type":"redirect","status":303,     |
      |    "location":"/meters"}               |
```

### 2.3 Key Discovery: SvelteKit CSRF Protection
A raw `curl` or HTTP client POST to `/login` initially fails with:
```http
HTTP/1.1 403 Forbidden
Content-Type: text/plain

Cross-site POST form submissions are forbidden
```
**Mechanism:** SvelteKit's default form submission security requires that the `Origin` and `Referer` headers match the host domain (`https://urja-ops.flockenergy.tech`).  
**Remediation in API Adapter:** The client adapter explicitly attaches:
- `Origin: https://urja-ops.flockenergy.tech`
- `Referer: https://urja-ops.flockenergy.tech/login`
- `Content-Type: application/x-www-form-urlencoded`

### 2.4 Session Cookie Lifecycle
- **Cookie Name:** `__Secure-better-auth.session_token`
- **Attributes:** `Max-Age=3600` (1 hour TTL), `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`
- **Session Expiration Behavior:**
  - On internal JSON endpoints (`/portal/*`): Returns `401 Unauthorized` with `{"error":"unauthorized","message":"A valid session is required."}`.
  - On SSR page routes (`/meters`, `/transformers`): Returns `302 Found` with `Location: /login`.
- **API Auto-Reauthentication:** The client adapter intercepts both 401 statuses and 302 redirects to `/login`, acquires a thread lock, issues a fresh login POST, updates the cookie jar, and retries the original request seamlessly.

---

## 3. Discovered Endpoints & Protocol Specifications

### 3.1 Meter Search (`/portal/meters/search`)
- **HTTP Method:** `GET`
- **URL:** `/portal/meters/search?q={query}&page={page}`
- **Authentication:** Required (`__Secure-better-auth.session_token`)
- **Query Parameters:**
  - `q` (string, optional): Search string. Matches against `meterId` (e.g. `J100000`) or `serialNo` (e.g. `SE33962`). Note: Does **not** match maker, DT code, or phase.
  - `page` (integer, default 1): 1-indexed page number.
  - `pageSize` (integer): Fixed by server to `20` records per page (attempts to pass `pageSize=500` are ignored).
- **Sample Response:**
```json
{
  "data": [
    {
      "meterId": "J100000",
      "serialNo": "SE33962",
      "make": "HPL",
      "phaseType": "single",
      "installStatus": "Decommissioned",
      "dtCode": "DT-001"
    }
  ],
  "total": 403,
  "page": 1,
  "pageSize": 20
}
```

---

### 3.2 Meter GPS Location (`/portal/meters/{id}/geo`)
- **HTTP Method:** `GET`
- **URL:** `/portal/meters/{meter_id}/geo`
- **Authentication:** Required
- **Sample Response:**
```json
{
  "data": {
    "latitude": "26.938961002479868",
    "longitude": "75.83095696146852"
  }
}
```
- **Quirk:** Coordinates are returned as unparsed floating-point strings. The adapter parses them to standard IEEE 754 floats.

---

### 3.3 Meter Consumption History (`/portal/meters/{id}/energy`)
- **HTTP Method:** `GET`
- **URL:** `/portal/meters/{meter_id}/energy`
- **Authentication:** Required
- **Granularity:** 30-minute intervals spanning 7 days (exactly 337 readings per meter).
- **Sample Response:**
```json
{
  "data": [
    {
      "timestamp": "23/06/2026 23:30",
      "kwh": "48438.74",
      "kvah": "52313.84",
      "voltR": "226"
    },
    {
      "timestamp": "30/06/2026 23:30",
      "kwh": "48580.79",
      "kvah": "52467.25",
      "voltR": "220"
    }
  ]
}
```
- **Quirks & Normalization:**
  - Date format is `DD/MM/YYYY HH:mm` in Indian Standard Time (IST, UTC+05:30). The API converts this to ISO 8601 (`YYYY-MM-DDTHH:mm:ss+05:30`).
  - `kwh`, `kvah`, and `voltR` are strings and may contain formatting artifacts. The API normalizes them into floats.

---

### 3.4 Distribution Transformers (`/portal/dts`)
- **HTTP Method:** `GET`
- **URL:** `/portal/dts?page={page}`
- **Authentication:** Required
- **Total Records:** 40 Distribution Transformers across Jaipur.
- **Sample Response:**
```json
{
  "data": [
    {
      "code": "DT-001",
      "name": "Malviya Nagar DT 1",
      "feederCode": "F-001",
      "capacityKva": 100
    }
  ],
  "total": 40,
  "page": 1,
  "pageSize": 20
}
```

---

### 3.5 Bulk Dataset Export & HMAC Signature Pipeline (`/portal/keys` & `/portal/export`)

This is the most critical architectural discovery made through inspecting bundle `nodes/4.2Bgc2kUI.js`. The portal provides an operator export feature:

#### Step 1: Obtain the Signing Secret
- **Endpoint:** `GET /portal/keys`
- **Response:**
```json
{
  "data": {
    "signingSecret": "I3dZPPf5CgTp7JyGNMI8i6z8LFR7TmSR"
  }
}
```

#### Step 2: Calculate the HMAC-SHA256 Signature
- **Payload String to Sign:**
  ```
  GET\n/portal/export\npage=1\n<UNIX_TIMESTAMP>
  ```
  *(Four lines separated by newline: HTTP method, path, query string, and integer epoch timestamp).*
- **Algorithm:** `HMAC-SHA256(secret=signingSecret, message=payload)`
- **Header Output:**
  - `x-timestamp`: `<UNIX_TIMESTAMP>`
  - `x-signature`: `<HEX_DIGEST>`

#### Step 3: Fetch `/portal/export?page=1`
- **Response:** Yields **all 403 meters** with complete metadata in a single response payload:
```json
{
  "total": 403,
  "data": [
    {
      "meterId": "J100000",
      "serialNo": "SE33962",
      "make": "HPL",
      "phaseType": "single",
      "installStatus": "Decommissioned",
      "installType": "Whole Current",
      "build": "legacy",
      "dtCode": "DT-001",
      "hierarchy": {
        "zone": { "name": "Jaipur Zone 1", "code": "Z-01" },
        "circle": { "name": "Circle 1", "code": "C-01" },
        "division": { "name": "Division 1", "code": "D-01" },
        "subdivision": { "name": "Subdivision 1", "code": "SD-01" },
        "substation": { "name": "Substation 1", "code": "SS-01" },
        "feeder": { "name": "Feeder 1", "code": "F-001" },
        "dt": { "name": "Malviya Nagar DT 1", "code": "DT-001" }
      },
      "geo": {
        "lat": 26.938961002479868,
        "lng": 75.83095696146852
      }
    }
  ]
}
```

---

## 4. Legacy Data Anomalies & Normalization Rules

### 4.1 Dual Build Generations (`legacy` vs `v2`)
In the dataset of 403 meters:
- **`legacy` (238 meters):** Nameplate parameters on `/meters/{id}` are stored as an array of objects:
  ```json
  [
    {"parameterName": "Meter ID", "parameterValue": "J100000"},
    {"parameterName": "Serial No", "parameterValue": "SE33962"}
  ]
  ```
- **`v2` (165 meters):** Nameplate parameters are stored in a nested, string-escaped JSON string inside `classData`:
  ```json
  {
    "classData": "{\"installed_meter\":{\"MeterId\":\"J100004\",\"SerialNo\":\"SE65293\",\"Make\":\"Genus\",\"PhaseType\":\"single\",\"InstallationStatus\":\"Faulty\",\"InstallationType\":\"CT Operated\"}}"
  }
  ```
**Normalization Strategy:** The adapter detects `classData` vs `data` and standardizes all outputs into a unified dictionary and typed Pydantic models.

---

### 4.2 The 22 Hierarchy Inconsistencies & Reconciler
A systematic integrity audit of the 403 meters revealed **22 records** with missing hierarchy attributes:

| Meter ID | Node Level | Legacy Raw State | Reconciled / Healed State | Healing Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **J100011** | Circle | `name: 'Circle 6', code: ''` | `name: 'Circle 6', code: 'C-06'` | Inferred from Circle index |
| **J100044** | Feeder | `name: 'Feeder 5', code: ''` | `name: 'Feeder 5', code: 'F-005'` | Inferred from Feeder index |
| **J100074** | Circle | `name: 'Circle 5', code: ''` | `name: 'Circle 5', code: 'C-05'` | Inferred from Circle index |
| **J100078** | Feeder | `name: 'Feeder 11', code: ''` | `name: 'Feeder 11', code: 'F-011'` | Inferred from Feeder index |
| **J100097** | Circle | `name: 'Circle 6', code: ''` | `name: 'Circle 6', code: 'C-06'` | Inferred from Circle index |
| **J100116** | Circle | `name: 'Circle 1', code: ''` | `name: 'Circle 1', code: 'C-01'` | Inferred from Circle index |
| **J100134** | Feeder | `name: 'Feeder 15', code: ''` | `name: 'Feeder 15', code: 'F-015'` | Inferred from Feeder index |
| **J100153** | Substation | `name: 'Substation 16', code: ''` | `name: 'Substation 16', code: 'SS-16'` | Inferred from Substation index |
| **J100162** | Feeder | `name: '', code: 'F-003'` | `name: 'Feeder 3', code: 'F-003'` | Inferred from Code reverse lookup |
| **J100170** | Circle | `name: 'Circle 5', code: ''` | `name: 'Circle 5', code: 'C-05'` | Inferred from Circle index |
| **J100210** | Feeder | `name: 'Feeder 11', code: ''` | `name: 'Feeder 11', code: 'F-011'` | Inferred from Feeder index |
| **J100218** | Circle | `name: '', code: 'C-01'` | `name: 'Circle 1', code: 'C-01'` | Inferred from Code reverse lookup |
| **J100228** | Substation | `name: 'Substation 11', code: ''` | `name: 'Substation 11', code: 'SS-11'` | Inferred from Substation index |
| **J100248** | Circle | `name: '', code: 'C-03'` | `name: 'Circle 3', code: 'C-03'` | Inferred from Code reverse lookup |
| **J100257** | Feeder | `name: '', code: 'F-018'` | `name: 'Feeder 18', code: 'F-018'` | Inferred from Code reverse lookup |
| **J100265** | Circle | `name: 'Circle 2', code: ''` | `name: 'Circle 2', code: 'C-02'` | Inferred from Circle index |
| **J100268** | Feeder | `name: 'Feeder 1', code: ''` | `name: 'Feeder 1', code: 'F-001'` | Inferred from Feeder index |
| **J100302** | Substation | `name: 'Substation 5', code: ''` | `name: 'Substation 5', code: 'SS-05'` | Inferred from Substation index |
| **J100306** | Circle | `name: '', code: 'C-03'` | `name: 'Circle 3', code: 'C-03'` | Inferred from Code reverse lookup |
| **J100370** | Circle | `name: '', code: 'C-05'` | `name: 'Circle 5', code: 'C-05'` | Inferred from Code reverse lookup |
| **J100371** | Circle | `name: '', code: 'C-06'` | `name: 'Circle 6', code: 'C-06'` | Inferred from Code reverse lookup |
| **J100372** | Feeder | `name: '', code: 'F-013'` | `name: 'Feeder 13', code: 'F-013'` | Inferred from Code reverse lookup |

**Resolution:** The `HierarchyEngine` (`app/hierarchy.py`) constructs bidirectional mapping dictionaries (`name <-> code`) by collecting all unambiguous sister nodes in the network topology. During normalization, any node with a missing name or code is automatically healed, with `is_healed: true` recorded on the node schema.

---

## 5. Architectural Comparison: Legacy Portal vs Wrapper API

| Capability | Legacy Urja Ops Portal | Flock Energy REST API Wrapper |
| :--- | :--- | :--- |
| **Interface** | HTML Web Browser UI only | Documented REST API + Interactive OpenAPI / Scalar / Swagger |
| **Authentication** | Manual browser login form with CSRF session cookies | Automated persistent session with silent transparent re-authentication |
| **Data Formats** | Unquoted strings, nested JSON in strings, non-standard dates | Strongly typed JSON, ISO 8601 timestamps, IEEE floats |
| **Bulk Access** | Hidden behind HMAC signing mechanism | First-class `GET /api/v1/export` & fast in-memory query engine |
| **Search Capabilities** | Prefix search on meter ID or serial only | Multi-attribute search (make, phase, status, DT, feeder, zone) |
| **Spatial Queries** | None | Haversine proximity query (`near_lat`, `near_lng`, `radius_km`) |
| **Network Hierarchy** | Breadcrumb text string on detail page | Complete 7-tier nested tree endpoint with healed anomalies |
| **Consumption Stats** | Raw unaggregated table (337 rows) | Cumulative consumption delta, voltage stats, min/max metrics |
