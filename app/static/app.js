// Urja Meter Ops Modern API Dashboard Frontend

let currentPage = 1;
const pageSize = 20;
let currentMeterId = "J100000";

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initEventListeners();
  loadAnalyticsSummary();
  loadMeters(1);
  loadHierarchy();
  loadTransformers();
  loadAnomaliesInspector();
  loadConsumption("J100000");
});

// -----------------------------------------------------------------------------
// Tab Switching
// -----------------------------------------------------------------------------
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }
    });
  });
}

// -----------------------------------------------------------------------------
// Event Listeners
// -----------------------------------------------------------------------------
function initEventListeners() {
  document.getElementById("btn-apply-filters").addEventListener("click", () => {
    currentPage = 1;
    loadMeters(1);
  });

  document.getElementById("btn-reset-filters").addEventListener("click", () => {
    document.getElementById("meter-search-input").value = "";
    document.getElementById("filter-make").value = "";
    document.getElementById("filter-status").value = "";
    document.getElementById("filter-phase").value = "";
    document.getElementById("filter-build").value = "";
    currentPage = 1;
    loadMeters(1);
  });

  document.getElementById("meter-search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      currentPage = 1;
      loadMeters(1);
    }
  });

  document.getElementById("btn-prev-page").addEventListener("click", () => {
    if (currentPage > 1) {
      loadMeters(currentPage - 1);
    }
  });

  document.getElementById("btn-next-page").addEventListener("click", () => {
    loadMeters(currentPage + 1);
  });

  document.getElementById("btn-load-consumption").addEventListener("click", () => {
    const val = document.getElementById("consumption-meter-input").value.trim();
    if (val) {
      loadConsumption(val);
    }
  });

  document.getElementById("btn-run-proximity").addEventListener("click", runProximitySearch);

  document.getElementById("btn-refresh-cache").addEventListener("click", async () => {
    const btn = document.getElementById("btn-refresh-cache");
    btn.textContent = "⏳ Refreshing...";
    btn.disabled = true;
    try {
      const res = await fetch("/api/v1/cache/refresh", { method: "POST" });
      if (res.ok) {
        alert("Cache successfully refreshed from Urja portal!");
        loadAnalyticsSummary();
        loadMeters(currentPage);
        loadHierarchy();
      } else {
        alert("Refresh failed.");
      }
    } catch (err) {
      alert("Error refreshing cache: " + err);
    } finally {
      btn.textContent = "🔄 Refresh Cache";
      btn.disabled = false;
    }
  });

  // Modal close
  document.getElementById("modal-close-btn").addEventListener("click", closeModal);
  document.getElementById("meter-modal").addEventListener("click", (e) => {
    if (e.target.id === "meter-modal") closeModal();
  });

  document.getElementById("modal-view-consumption-btn").addEventListener("click", () => {
    closeModal();
    // Switch to consumption tab
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

    const tabBtn = document.querySelector('[data-tab="tab-consumption"]');
    if (tabBtn) tabBtn.classList.add("active");
    const panel = document.getElementById("tab-consumption");
    if (panel) panel.classList.add("active");

    document.getElementById("consumption-meter-input").value = currentMeterId;
    loadConsumption(currentMeterId);
  });
}

function closeModal() {
  document.getElementById("meter-modal").classList.remove("active");
}

// -----------------------------------------------------------------------------
// Analytics KPI Cards
// -----------------------------------------------------------------------------
async function loadAnalyticsSummary() {
  try {
    const res = await fetch("/api/v1/analytics/summary");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("kpi-total-meters").textContent = data.total_meters;
    
    const installed = data.by_status["Installed"] || 0;
    const installedPct = Math.round((installed / data.total_meters) * 100);
    document.getElementById("kpi-installed-meters").textContent = `${installed} (${installedPct}%)`;

    const faulty = data.by_status["Faulty"] || 0;
    const faultyPct = Math.round((faulty / data.total_meters) * 100);
    document.getElementById("kpi-faulty-meters").textContent = `${faulty} (${faultyPct}%)`;

    document.getElementById("kpi-total-dts").textContent = data.total_transformers;
    document.getElementById("kpi-dts-sub").textContent = `Total Capacity: ${data.total_transformer_capacity_kva.toLocaleString()} kVA`;

    document.getElementById("kpi-healed-anomalies").textContent = data.healed_hierarchy_anomalies;
  } catch (err) {
    console.error("Failed to load analytics summary:", err);
  }
}

// -----------------------------------------------------------------------------
// Smart Meters Table & Pagination
// -----------------------------------------------------------------------------
async function loadMeters(page = 1) {
  const tbody = document.getElementById("meters-tbody");
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 2rem;">Loading smart meters...</td></tr>';

  const q = document.getElementById("meter-search-input").value.trim();
  const make = document.getElementById("filter-make").value;
  const status = document.getElementById("filter-status").value;
  const phase = document.getElementById("filter-phase").value;
  const build = document.getElementById("filter-build").value;

  const params = new URLSearchParams({
    page: page,
    page_size: pageSize,
  });
  if (q) params.set("q", q);
  if (make) params.set("make", make);
  if (status) params.set("install_status", status);
  if (phase) params.set("phase_type", phase);
  if (build) params.set("build", build);

  try {
    const res = await fetch(`/api/v1/meters?${params.toString()}`);
    if (!res.ok) throw new Error("Status " + res.status);
    const data = await res.json();

    currentPage = data.page;
    document.getElementById("pagination-text").textContent = `Page ${data.page} of ${data.total_pages} (${data.total} meters)`;
    document.getElementById("btn-prev-page").disabled = (data.page <= 1);
    document.getElementById("btn-next-page").disabled = (data.page >= data.total_pages);

    if (data.data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 2rem; color:var(--text-muted);">No meters found matching your filter criteria.</td></tr>';
      return;
    }

    tbody.innerHTML = "";
    data.data.forEach(m => {
      const tr = document.createElement("tr");

      let statusClass = "status-installed";
      if (m.install_status === "Faulty") statusClass = "status-faulty";
      else if (m.install_status === "Decommissioned") statusClass = "status-decommissioned";

      tr.innerHTML = `
        <td style="font-weight:600;"><a href="javascript:void(0)" onclick="openMeterModal('${m.meter_id}')" style="color:var(--accent-cyan); text-decoration:none;">${m.meter_id}</a></td>
        <td style="color:var(--text-secondary);">${m.serial_number}</td>
        <td>${m.make}</td>
        <td><span style="text-transform:capitalize;">${m.phase_type}</span></td>
        <td><span class="status-badge ${statusClass}">${m.install_status}</span></td>
        <td><span style="font-family:monospace; color:var(--accent-blue);">${m.dt_code}</span></td>
        <td><span style="font-size:0.75rem; color:var(--text-muted);">${m.build || "legacy"}</span></td>
        <td>
          <button class="btn btn-secondary" style="padding:0.25rem 0.5rem; font-size:0.75rem;" onclick="openMeterModal('${m.meter_id}')">
            Details
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--accent-rose); padding: 2rem;">Error loading meters: ${err.message}</td></tr>`;
  }
}

// -----------------------------------------------------------------------------
// Meter Details Modal
// -----------------------------------------------------------------------------
async function openMeterModal(meterId) {
  currentMeterId = meterId;
  const modal = document.getElementById("meter-modal");
  modal.classList.add("active");

  document.getElementById("modal-meter-title").textContent = `Meter ${meterId}`;
  document.getElementById("modal-meter-sub").textContent = "Loading meter details...";
  document.getElementById("modal-breadcrumbs").innerHTML = "Loading hierarchy...";
  document.getElementById("modal-nameplate").innerHTML = "Loading nameplate...";
  document.getElementById("modal-location").innerHTML = "Loading coordinates...";

  try {
    const res = await fetch(`/api/v1/meters/${meterId}`);
    if (!res.ok) throw new Error("Meter not found");
    const m = await res.json();

    document.getElementById("modal-meter-sub").textContent = `Serial: ${m.serial_number} · Make: ${m.make} · Status: ${m.install_status}`;

    // Hierarchy breadcrumbs
    const bc = document.getElementById("modal-breadcrumbs");
    bc.innerHTML = "";
    if (m.hierarchy) {
      const levels = ["zone", "circle", "division", "subdivision", "substation", "feeder", "dt"];
      levels.forEach((lvl, idx) => {
        const node = m.hierarchy[lvl];
        if (node) {
          const span = document.createElement("span");
          span.style.background = "var(--bg-card)";
          span.style.padding = "0.25rem 0.5rem";
          span.style.borderRadius = "0.25rem";
          span.style.border = "1px solid var(--border-color)";
          span.innerHTML = `<strong>${lvl.toUpperCase()}:</strong> ${node.name} (${node.code})`;
          if (node.is_healed) {
            span.innerHTML += `<span class="badge-healed">Healed</span>`;
          }
          bc.appendChild(span);
          if (idx < levels.length - 1) {
            const arrow = document.createElement("span");
            arrow.textContent = "›";
            arrow.style.color = "var(--text-muted)";
            bc.appendChild(arrow);
          }
        }
      });
    }

    // Nameplate
    const np = document.getElementById("modal-nameplate");
    np.innerHTML = `
      <div style="display:flex; justify-content:space-between; padding:0.35rem 0; border-bottom:1px solid var(--border-color);"><span style="color:var(--text-secondary);">Phase Configuration</span><span>${m.phase_type}</span></div>
      <div style="display:flex; justify-content:space-between; padding:0.35rem 0; border-bottom:1px solid var(--border-color);"><span style="color:var(--text-secondary);">Installation Type</span><span>${m.install_type || "Whole Current"}</span></div>
      <div style="display:flex; justify-content:space-between; padding:0.35rem 0; border-bottom:1px solid var(--border-color);"><span style="color:var(--text-secondary);">Connected DT Code</span><span style="font-family:monospace; color:var(--accent-blue);">${m.dt_code}</span></div>
      <div style="display:flex; justify-content:space-between; padding:0.35rem 0; border-bottom:1px solid var(--border-color);"><span style="color:var(--text-secondary);">Build Version</span><span>${m.build || "legacy"}</span></div>
    `;

    // Location
    const loc = document.getElementById("modal-location");
    if (m.geo) {
      loc.innerHTML = `
        <div style="font-size:1.1rem; font-weight:600; color:var(--accent-cyan); margin-bottom:0.25rem;">
          ${m.geo.latitude.toFixed(6)}° N, ${m.geo.longitude.toFixed(6)}° E
        </div>
        <p style="font-size:0.75rem; color:var(--text-muted);">Jaipur Distribution Area · WGS84 Datum</p>
        <a href="https://www.google.com/maps?q=${m.geo.latitude},${m.geo.longitude}" target="_blank" class="btn btn-outline" style="margin-top:0.75rem; display:inline-flex;">
          🗺️ View on Google Maps
        </a>
      `;
    } else {
      loc.innerHTML = `<span style="color:var(--text-muted);">No GPS coordinates available.</span>`;
    }

  } catch (err) {
    document.getElementById("modal-meter-sub").textContent = "Error loading meter details: " + err.message;
  }
}

// -----------------------------------------------------------------------------
// Consumption History & Canvas Chart Visualizer
// -----------------------------------------------------------------------------
async function loadConsumption(meterId) {
  try {
    const res = await fetch(`/api/v1/meters/${meterId}/consumption`);
    if (!res.ok) throw new Error("Status " + res.status);
    const data = await res.json();

    const stats = data.stats;
    document.getElementById("cons-total-kwh").textContent = `${stats.kwh_total_consumed} kWh`;
    document.getElementById("cons-avg-v").textContent = `${stats.avg_voltage} V`;
    document.getElementById("cons-range-v").textContent = `${stats.min_voltage}V - ${stats.max_voltage}V`;
    document.getElementById("cons-readings-count").textContent = `${stats.reading_count} points (7 days)`;

    // Render Canvas Chart
    renderConsumptionChart(data.readings);

    // Render table sample (latest 10)
    const tbody = document.getElementById("consumption-tbody");
    tbody.innerHTML = "";
    const sample = data.readings.slice(-10).reverse();
    sample.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-family:monospace; font-size:0.8rem;">${r.timestamp}</td>
        <td style="color:var(--text-muted);">${r.raw_timestamp}</td>
        <td style="font-weight:600; color:var(--accent-cyan);">${r.kwh}</td>
        <td>${r.kvah}</td>
        <td style="color:var(--accent-amber);">${r.volt_r} V</td>
      `;
      tbody.appendChild(tr);
    });

  } catch (err) {
    console.error("Error loading consumption:", err);
    document.getElementById("consumption-tbody").innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--accent-rose);">Failed to load consumption: ${err.message}</td></tr>`;
  }
}

function renderConsumptionChart(readings) {
  const canvas = document.getElementById("consumption-canvas");
  if (!canvas || !readings || readings.length === 0) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;

  // Clear
  ctx.clearRect(0, 0, width, height);

  const padding = { top: 30, right: 60, bottom: 40, left: 60 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Min and max for kWh and Voltage
  const kwhVals = readings.map(r => r.kwh);
  const voltVals = readings.map(r => r.volt_r);

  const minKwh = Math.min(...kwhVals);
  const maxKwh = Math.max(...kwhVals);
  const kwhRange = (maxKwh - minKwh) || 1;

  const minVolt = Math.min(...voltVals) - 5;
  const maxVolt = Math.max(...voltVals) + 5;
  const voltRange = (maxVolt - minVolt) || 1;

  // Background Grid Lines
  ctx.strokeStyle = "#374151";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);

  const gridSteps = 4;
  for (let i = 0; i <= gridSteps; i++) {
    const y = padding.top + (chartH / gridSteps) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();

    // kWh label (left)
    const valKwh = maxKwh - (kwhRange / gridSteps) * i;
    ctx.fillStyle = "#06b6d4";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(valKwh.toFixed(1), padding.left - 8, y + 3);

    // Voltage label (right)
    const valVolt = maxVolt - (voltRange / gridSteps) * i;
    ctx.fillStyle = "#f59e0b";
    ctx.textAlign = "left";
    ctx.fillText(`${valVolt.toFixed(0)} V`, width - padding.right + 8, y + 3);
  }
  ctx.setLineDash([]);

  // Plot kWh line (Cyan)
  ctx.beginPath();
  ctx.strokeStyle = "#06b6d4";
  ctx.lineWidth = 2.5;

  readings.forEach((r, idx) => {
    const x = padding.left + (chartW / (readings.length - 1)) * idx;
    const y = padding.top + chartH - ((r.kwh - minKwh) / kwhRange) * chartH;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Plot Voltage line (Amber)
  ctx.beginPath();
  ctx.strokeStyle = "#f59e0b";
  ctx.lineWidth = 1.5;

  readings.forEach((r, idx) => {
    const x = padding.left + (chartW / (readings.length - 1)) * idx;
    const y = padding.top + chartH - ((r.volt_r - minVolt) / voltRange) * chartH;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Legend
  ctx.fillStyle = "#06b6d4";
  ctx.fillRect(width / 2 - 120, 10, 14, 4);
  ctx.font = "11px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Active Energy (kWh)", width / 2 - 100, 16);

  ctx.fillStyle = "#f59e0b";
  ctx.fillRect(width / 2 + 30, 10, 14, 4);
  ctx.fillText("R-Phase Voltage (V)", width / 2 + 50, 16);

  // Time labels at bottom
  ctx.fillStyle = "#9ca3af";
  ctx.textAlign = "center";
  ctx.fillText(readings[0].raw_timestamp, padding.left + 30, height - 10);
  ctx.fillText(readings[Math.floor(readings.length / 2)].raw_timestamp, width / 2, height - 10);
  ctx.fillText(readings[readings.length - 1].raw_timestamp, width - padding.right - 30, height - 10);
}

// -----------------------------------------------------------------------------
// Network Hierarchy Tree
// -----------------------------------------------------------------------------
async function loadHierarchy() {
  const container = document.getElementById("hierarchy-tree-container");
  try {
    const res = await fetch("/api/v1/hierarchy");
    if (!res.ok) throw new Error("Status " + res.status);
    const tree = await res.json();

    container.innerHTML = "";
    tree.forEach(rootNode => {
      container.appendChild(createTreeNodeElement(rootNode, 0));
    });
  } catch (err) {
    container.innerHTML = `<span style="color:var(--accent-rose);">Failed to load hierarchy: ${err.message}</span>`;
  }
}

function createTreeNodeElement(node, depth) {
  const el = document.createElement("div");
  el.className = "tree-node";
  if (depth === 0) el.style.marginLeft = "0";

  const header = document.createElement("div");
  header.className = "node-header";

  const hasChildren = node.children && node.children.length > 0;
  const toggleIcon = hasChildren ? "▾ " : "• ";

  header.innerHTML = `
    <span style="color:var(--accent-cyan); font-family:monospace;">${toggleIcon}</span>
    <span class="node-level-tag">${node.level}</span>
    <span class="node-title">${node.name} (${node.code})</span>
    <span class="badge" style="background:var(--bg-hover); color:var(--text-secondary);">${node.meter_count} meters</span>
  `;

  el.appendChild(header);

  if (hasChildren) {
    const childrenContainer = document.createElement("div");
    childrenContainer.className = "node-children";

    // Auto collapse after depth 2 for readability
    if (depth >= 2) {
      childrenContainer.style.display = "none";
      header.querySelector("span").textContent = "▸ ";
    }

    header.addEventListener("click", () => {
      const isHidden = childrenContainer.style.display === "none";
      childrenContainer.style.display = isHidden ? "block" : "none";
      header.querySelector("span").textContent = isHidden ? "▾ " : "▸ ";
    });

    node.children.forEach(child => {
      childrenContainer.appendChild(createTreeNodeElement(child, depth + 1));
    });
    el.appendChild(childrenContainer);
  }

  return el;
}

// -----------------------------------------------------------------------------
// Spatial / Proximity Search
// -----------------------------------------------------------------------------
function setProximityPreset(lat, lng, name) {
  document.getElementById("prox-lat").value = lat;
  document.getElementById("prox-lng").value = lng;
  document.getElementById("prox-radius").value = 5.0;
  runProximitySearch();
}

async function runProximitySearch() {
  const lat = parseFloat(document.getElementById("prox-lat").value);
  const lng = parseFloat(document.getElementById("prox-lng").value);
  const radius = parseFloat(document.getElementById("prox-radius").value);
  const tbody = document.getElementById("proximity-tbody");

  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 2rem;">Computing spatial proximity...</td></tr>';

  try {
    const res = await fetch(`/api/v1/meters?near_lat=${lat}&near_lng=${lng}&radius_km=${radius}&sort_by=distance&page_size=50`);
    if (!res.ok) throw new Error("Status " + res.status);
    const data = await res.json();

    if (data.data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 2rem; color:var(--text-muted);">No smart meters found within ${radius} km radius of (${lat}, ${lng}).</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    data.data.forEach(m => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight:600;"><a href="javascript:void(0)" onclick="openMeterModal('${m.meter_id}')" style="color:var(--accent-cyan); text-decoration:none;">${m.meter_id}</a></td>
        <td style="color:var(--text-secondary);">${m.serial_number}</td>
        <td>${m.make}</td>
        <td>${m.phase_type}</td>
        <td><span class="status-badge status-installed">${m.install_status}</span></td>
        <td><span style="font-family:monospace; color:var(--accent-blue);">${m.dt_code}</span></td>
        <td style="font-weight:600; color:var(--accent-emerald);">~ Within ${radius} km</td>
        <td>
          <button class="btn btn-secondary" style="padding:0.25rem 0.5rem; font-size:0.75rem;" onclick="openMeterModal('${m.meter_id}')">
            View
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--accent-rose);">Proximity error: ${err.message}</td></tr>`;
  }
}

// -----------------------------------------------------------------------------
// Distribution Transformers
// -----------------------------------------------------------------------------
async function loadTransformers() {
  const grid = document.getElementById("transformers-grid");
  try {
    const res = await fetch("/api/v1/transformers?page_size=50");
    if (!res.ok) return;
    const data = await res.json();

    grid.innerHTML = "";
    data.data.forEach(dt => {
      const card = document.createElement("div");
      card.className = "dt-card";
      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
          <span style="font-family:monospace; font-weight:700; color:var(--accent-cyan);">${dt.code}</span>
          <span class="badge" style="background:rgba(59, 130, 246, 0.2); color:#60a5fa;">${dt.capacity_kva} kVA</span>
        </div>
        <div style="font-weight:600; margin-bottom:0.25rem;">${dt.name}</div>
        <div style="font-size:0.8rem; color:var(--text-secondary); margin-bottom:0.75rem;">Feeder: <span style="font-family:monospace;">${dt.feeder_code}</span></div>
        <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.8rem; border-top:1px solid var(--border-color); padding-top:0.5rem;">
          <span style="color:var(--text-muted);">${dt.meter_count} Connected Meters</span>
          <button class="btn btn-outline" style="padding:0.2rem 0.5rem; font-size:0.75rem;" onclick="filterByDt('${dt.code}')">
            Explore Meters →
          </button>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch (err) {
    grid.innerHTML = `<span>Error loading transformers: ${err.message}</span>`;
  }
}

function filterByDt(dtCode) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));

  const tabBtn = document.querySelector('[data-tab="tab-meters"]');
  if (tabBtn) tabBtn.classList.add("active");
  const panel = document.getElementById("tab-meters");
  if (panel) panel.classList.add("active");

  document.getElementById("meter-search-input").value = "";
  document.getElementById("filter-status").value = "";
  document.getElementById("filter-make").value = "";
  document.getElementById("filter-phase").value = "";
  document.getElementById("filter-build").value = "";

  // Query by dt_code directly
  fetch(`/api/v1/meters?dt_code=${dtCode}&page=1&page_size=50`)
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById("meters-tbody");
      tbody.innerHTML = "";
      document.getElementById("pagination-text").textContent = `Meters attached to ${dtCode} (${data.total} meters)`;
      data.data.forEach(m => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td style="font-weight:600;"><a href="javascript:void(0)" onclick="openMeterModal('${m.meter_id}')" style="color:var(--accent-cyan); text-decoration:none;">${m.meter_id}</a></td>
          <td style="color:var(--text-secondary);">${m.serial_number}</td>
          <td>${m.make}</td>
          <td>${m.phase_type}</td>
          <td><span class="status-badge status-installed">${m.install_status}</span></td>
          <td><span style="font-family:monospace; color:var(--accent-blue);">${m.dt_code}</span></td>
          <td>${m.build || "legacy"}</td>
          <td>
            <button class="btn btn-secondary" style="padding:0.25rem 0.5rem; font-size:0.75rem;" onclick="openMeterModal('${m.meter_id}')">
              Details
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    });
}

// -----------------------------------------------------------------------------
// Protocol & Anomalies Inspector
// -----------------------------------------------------------------------------
function loadAnomaliesInspector() {
  const tbody = document.getElementById("anomalies-tbody");
  // The 22 legacy anomalies discovered during our reverse-engineering audit
  const anomaliesData = [
    { meterId: "J100011", level: "Circle", raw: "{name: 'Circle 6', code: ''}", healed: "code: 'C-06', name: 'Circle 6'" },
    { meterId: "J100044", level: "Feeder", raw: "{name: 'Feeder 5', code: ''}", healed: "code: 'F-005', name: 'Feeder 5'" },
    { meterId: "J100074", level: "Circle", raw: "{name: 'Circle 5', code: ''}", healed: "code: 'C-05', name: 'Circle 5'" },
    { meterId: "J100078", level: "Feeder", raw: "{name: 'Feeder 11', code: ''}", healed: "code: 'F-011', name: 'Feeder 11'" },
    { meterId: "J100097", level: "Circle", raw: "{name: 'Circle 6', code: ''}", healed: "code: 'C-06', name: 'Circle 6'" },
    { meterId: "J100116", level: "Circle", raw: "{name: 'Circle 1', code: ''}", healed: "code: 'C-01', name: 'Circle 1'" },
    { meterId: "J100134", level: "Feeder", raw: "{name: 'Feeder 15', code: ''}", healed: "code: 'F-015', name: 'Feeder 15'" },
    { meterId: "J100153", level: "Substation", raw: "{name: 'Substation 16', code: ''}", healed: "code: 'SS-16', name: 'Substation 16'" },
    { meterId: "J100162", level: "Feeder", raw: "{name: '', code: 'F-003'}", healed: "code: 'F-003', name: 'Feeder 3'" },
    { meterId: "J100170", level: "Circle", raw: "{name: 'Circle 5', code: ''}", healed: "code: 'C-05', name: 'Circle 5'" },
    { meterId: "J100210", level: "Feeder", raw: "{name: 'Feeder 11', code: ''}", healed: "code: 'F-011', name: 'Feeder 11'" },
    { meterId: "J100218", level: "Circle", raw: "{name: '', code: 'C-01'}", healed: "code: 'C-01', name: 'Circle 1'" },
    { meterId: "J100228", level: "Substation", raw: "{name: 'Substation 11', code: ''}", healed: "code: 'SS-11', name: 'Substation 11'" },
    { meterId: "J100248", level: "Circle", raw: "{name: '', code: 'C-03'}", healed: "code: 'C-03', name: 'Circle 3'" },
    { meterId: "J100257", level: "Feeder", raw: "{name: '', code: 'F-018'}", healed: "code: 'F-018', name: 'Feeder 18'" },
    { meterId: "J100265", level: "Circle", raw: "{name: 'Circle 2', code: ''}", healed: "code: 'C-02', name: 'Circle 2'" },
    { meterId: "J100268", level: "Feeder", raw: "{name: 'Feeder 1', code: ''}", healed: "code: 'F-001', name: 'Feeder 1'" },
    { meterId: "J100302", level: "Substation", raw: "{name: 'Substation 5', code: ''}", healed: "code: 'SS-05', name: 'Substation 5'" },
    { meterId: "J100306", level: "Circle", raw: "{name: '', code: 'C-03'}", healed: "code: 'C-03', name: 'Circle 3'" },
    { meterId: "J100370", level: "Circle", raw: "{name: '', code: 'C-05'}", healed: "code: 'C-05', name: 'Circle 5'" },
    { meterId: "J100371", level: "Circle", raw: "{name: '', code: 'C-06'}", healed: "code: 'C-06', name: 'Circle 6'" },
    { meterId: "J100372", level: "Feeder", raw: "{name: '', code: 'F-013'}", healed: "code: 'F-013', name: 'Feeder 13'" },
  ];

  tbody.innerHTML = "";
  anomaliesData.forEach(a => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="font-weight:600;"><a href="javascript:void(0)" onclick="openMeterModal('${a.meterId}')" style="color:var(--accent-cyan);">${a.meterId}</a></td>
      <td><span class="node-level-tag">${a.level}</span></td>
      <td style="font-family:monospace; color:var(--accent-amber); font-size:0.8rem;">${a.raw}</td>
      <td style="font-family:monospace; color:var(--accent-emerald); font-size:0.8rem;">${a.healed}</td>
      <td><span class="badge-healed">✓ Healed Automatically</span></td>
    `;
    tbody.appendChild(tr);
  });
}
