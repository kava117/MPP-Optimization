/* ── FoodReach — app.js ──────────────────────────────────────────────────── */

const API = "http://localhost:5000/api";

// ── State ─────────────────────────────────────────────────────────────────

const state = {
  mode:           "driving",
  thresholdMiles: 5.0,
  algo:           "ilp",
  selectedZips:   new Set(),
  allZips:        [],
  lastResult:     null,
  zipGeoJSON:     null,
  radiusCircles:  [],
};

// ── Map Setup ─────────────────────────────────────────────────────────────

const map = L.map("map", { center: [28.55, -81.38], zoom: 11, zoomControl: false });
L.control.zoom({ position: "bottomright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>', maxZoom: 19, subdomains: 'abcd',
}).addTo(map);

const layers = {
  zips:     L.layerGroup().addTo(map),
  centers:  L.layerGroup().addTo(map),
  selected: L.layerGroup().addTo(map),
  edges:    L.layerGroup().addTo(map),
};
const layerVisible = { zips:true, centers:true, selected:true, edges:true };

// ── Icons ─────────────────────────────────────────────────────────────────

function makeIcon(color, size, ring) {
  const shadow = ring
    ? `box-shadow:0 0 0 3px ${color}55,0 2px 10px rgba(0,0,0,.7);`
    : `box-shadow:0 2px 6px rgba(0,0,0,.5);`;
  return L.divIcon({
    className:"",
    html:`<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid rgba(255,255,255,.3);${shadow}"></div>`,
    iconSize:[size,size], iconAnchor:[size/2,size/2],
  });
}
const ICON_CENTER   = makeIcon("#f0a500", 9,  false);
const ICON_COVERED  = makeIcon("#2dc98a", 9,  false);
const ICON_SELECTED = makeIcon("#1a1f6e", 16, true);

// ── Boot ──────────────────────────────────────────────────────────────────

async function init() {
  setStatus("Loading data…");
  try {
    await Promise.all([loadZipList(), loadZipPolygons(), loadAllCenters()]);
    setStatus("Ready");
  } catch(e) {
    setStatus("⚠ Server not reachable — start the backend first", true);
    document.getElementById("zipList").innerHTML =
      `<div class="zip-loading" style="color:#e63946">⚠ Cannot reach server.<br/>Run: <code>cd backend && python3 app.py</code></div>`;
  }
}

// ── Loaders ───────────────────────────────────────────────────────────────

async function loadZipList() {
  const data = await fetch(`${API}/zips`).then(r => r.json());
  state.allZips = data;
  data.forEach(z => state.selectedZips.add(z.zip));
  renderZipCheckboxes(data);
}

async function loadZipPolygons() {
  state.zipGeoJSON = await fetch(`${API}/zipcodes`).then(r => r.json());
  drawZipLayer({ covered: null });
}

async function loadAllCenters() {
  const geojson = await fetch(`${API}/centers`).then(r => r.json());
  layers.centers.clearLayers();
  geojson.features.forEach(f => {
    const [lon, lat] = f.geometry.coordinates;
    const { name, zip, address } = f.properties;
    L.marker([lat,lon], { icon: ICON_CENTER })
      .bindPopup(buildPopup({ name, zip, address, isSelected:false, isCovered:false, score:null }))
      .addTo(layers.centers);
  });
}

// ── ZIP Layer  ──────────────────

function drawZipLayer({ covered }) {
  if (!state.zipGeoJSON) return;
  layers.zips.clearLayers();
  const coveredSet = covered ? new Set(covered) : null;

  L.geoJSON(state.zipGeoJSON, {
    style: f => {
      const zip = f.properties.zip;
      if (!coveredSet)
        return { fillColor:"#4a90d9", fillOpacity:.06, color:"#4a90d9", weight:1.2, opacity:.4 };
      if (!state.selectedZips.has(zip))
        return { fillColor:"#555e75", fillOpacity:.03, color:"#555e75", weight:.7, opacity:.2 };
      return coveredSet.has(zip)
        ? { fillColor:"#2dc98a", fillOpacity:.15, color:"#2dc98a", weight:1.5, opacity:.7 }
        : { fillColor:"#ff6b6b", fillOpacity:.12, color:"#e63946", weight:1, opacity:.4 };
    },
    onEachFeature: (feature, layer) => {
      const { zip, center_count } = feature.properties;
      const isCov = coveredSet ? coveredSet.has(zip) : null;
      const badge = isCov === null ? "" : (isCov ? " ✓" : " ✗");
      const col   = isCov === null ? "#4a90d9" : isCov ? "#00e5a0" : "#e63946";
      layer.bindTooltip(
        `<div style="font-family:'DM Mono',monospace;font-size:12px;color:#e4e8f0;background:#13161e;padding:6px 10px;border-radius:6px;border:1px solid #252936">
          <strong style="color:${col}">${zip}${badge}</strong><br/>${center_count} center${center_count!==1?"s":""}
        </div>`, { sticky:true }
      );
      layer.on("click", () => highlightZip(zip));
    }
  }).addTo(layers.zips);
}

// ── Popup Builder ─────────────────────────────────────────────────────────

function buildPopup({ name, zip, address, isSelected, isCovered, score, breakdown }) {
  const statusLabel = isSelected ? "✓ Selected Stop" : isCovered ? "◎ Within coverage radius" : "◌ Candidate";
  const statusClass = isSelected ? "selected" : isCovered ? "covered" : "regular";

  let bdHTML = "";
  if (breakdown && Object.keys(breakdown).length > 0) {
    bdHTML = `<div style="margin-top:8px;padding-top:8px;border-top:1px solid #252936">
      <div style="font-family:'DM Mono',monospace;font-size:10px;color:#555e75;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px">Priority Breakdown</div>
      ${Object.entries(breakdown).map(([k,v]) =>
        `<div class="popup-row"><span>${k.replace(/_/g," ")}</span>${"▪".repeat(v)}<span style="color:#555e75"> ${v}/3</span></div>`
      ).join("")}
    </div>`;
  }

  return `<div class="popup-name">${name}</div>
    <div class="popup-row"><span>ZIP</span>${zip}</div>
    <div class="popup-row"><span>Address</span>${address}</div>
    ${score != null ? `<div class="popup-row"><span>Priority Score</span><strong style="color:#f0a500">${score}/18</strong></div>` : ""}
    ${bdHTML}
    <div style="margin-top:8px"><span class="popup-badge ${statusClass}">${statusLabel}</span></div>`;
}

// ── Results ───────────────────────────────────────────────────────────────

function renderResults(data) {
  state.lastResult = data;

  document.getElementById("statStops").textContent    = data.num_stops;
  document.getElementById("statCoverage").textContent = data.coverage_pct + "%";
  document.getElementById("statZips").textContent     = `${data.covered_zips.length}/${data.total_zips}`;
  document.getElementById("statMode").textContent     = data.mode.charAt(0).toUpperCase() + data.mode.slice(1);
  document.getElementById("statRadius").textContent   = data.threshold_miles + " mi";
  document.getElementById("statAlgoLabel").textContent = data.algorithm === "ilp_exact" ? "ILP Exact" : "Priority";

  const pct = data.coverage_pct;
  document.getElementById("coverageBarFill").style.width = pct + "%";
  document.getElementById("coverageBarFill").style.background =
    pct >= 90 ? "linear-gradient(90deg,#00b87d,#00e5a0)"
    : pct >= 70 ? "linear-gradient(90deg,#f0a500,#ffc244)"
    : "linear-gradient(90deg,#c0392b,#e63946)";
  document.getElementById("coverageBarLabel").textContent = pct + "%";

  document.getElementById("coveredZipChips").innerHTML = data.covered_zips.map(z =>
    `<div class="zip-chip" onclick="highlightZip('${z}')">${z}</div>`
  ).join("");

  const uncovered = [...state.selectedZips].filter(z => !data.covered_zips.includes(z));
  const el = document.getElementById("uncoveredZipsWrap");
  el.innerHTML = uncovered.length > 0
    ? `<h4 class="result-section-title" style="color:#e63946;margin-top:12px">Uncovered ZIPs (${uncovered.length})</h4>
       <div class="zip-chips">${uncovered.map(z =>
         `<div class="zip-chip" style="border-color:#e63946;color:#e63946" onclick="highlightZip('${z}')">${z}</div>`
       ).join("")}</div>`
    : `<div style="font-family:'DM Mono',monospace;font-size:11px;color:#00e5a0;margin-top:8px">✓ All selected ZIPs covered</div>`;

  document.getElementById("stopsList").innerHTML = data.selected_stops
    .sort((a,b) => (b.priority_score||0) - (a.priority_score||0))
    .map((s,i) => `
    <div class="stop-item" onclick="flyToStop(${s.lat},${s.lon},${JSON.stringify(s.name)})">
      <div class="stop-item-num">${i+1}</div>
      <div class="stop-item-body">
        <div class="stop-item-name">${s.name}</div>
        <div class="stop-item-meta">
          <span>ZIP ${s.zip}</span>
          ${s.priority_score!=null ? `<span class="stop-item-score">● Score ${s.priority_score}/18</span>` : ""}
        </div>
      </div>
    </div>`).join("");

  document.getElementById("resultsPlaceholder").classList.add("hidden");
  document.getElementById("resultsContent").classList.remove("hidden");

  renderMapResults(data);
  setStatus(`${data.num_stops} stops · ${data.coverage_pct}% coverage · ${data.mode}`);
}

function renderMapResults(data) {
  const selectedNames = new Set(data.selected_stops.map(s => s.name));
  const coveredZipSet = new Set(data.covered_zips);

  // Edges
  layers.edges.clearLayers();
  data.graph_edges.forEach(e => {
    L.polyline([[e.from_lat,e.from_lon],[e.to_lat,e.to_lon]],
      { color:"#4361ee", weight:1.5, opacity:.25, dashArray:"5,5" }
    ).bindTooltip(
      `<span style="font-family:'DM Mono',monospace;font-size:11px">${e.distance} mi</span>`,
      { sticky:true }
    ).addTo(layers.edges);
  });

  // Centers — redrawn with correct status icons
  layers.centers.clearLayers();
  layers.selected.clearLayers();
  data.all_centers.forEach(c => {
    const isSel = selectedNames.has(c.name);
    const isCov = coveredZipSet.has(c.zip) && !isSel;
    const icon  = isSel ? ICON_SELECTED : isCov ? ICON_COVERED : ICON_CENTER;
    L.marker([c.lat,c.lon], { icon, zIndexOffset: isSel ? 1000 : 0 })
      .bindPopup(buildPopup({
        name:c.name, zip:c.zip, address:c.address,
        isSelected:isSel, isCovered:isCov,
        score:c.priority_score, breakdown:c.priority_breakdown
      }))
      .addTo(layers.centers);
  });

  // ZIP polygons (no extra fetch — uses cached GeoJSON)
  drawZipLayer({ covered: data.covered_zips });

  // Fit bounds to selected stops
  if (data.selected_stops.length > 0) {
    map.fitBounds(
      L.latLngBounds(data.selected_stops.map(s => [s.lat,s.lon])).pad(0.15),
      { maxZoom:13, animate:true, duration:0.6 }
    );
  }
}

// ── Radius Preview ─────────────────────────────────────────────────────────

function showRadiusPreview() {
  clearRadiusPreview();
  if (!state.lastResult) return;
  const r = state.thresholdMiles * 1609.34;
  state.lastResult.selected_stops.forEach(s => {
    state.radiusCircles.push(
      L.circle([s.lat,s.lon], { radius:r, color:"#4361ee", fillColor:"#4361ee",
        fillOpacity:.05, weight:1, dashArray:"4,4" }).addTo(map)
    );
  });
}

function clearRadiusPreview() {
  state.radiusCircles.forEach(c => map.removeLayer(c));
  state.radiusCircles = [];
}

// ── Interactions ──────────────────────────────────────────────────────────

function flyToStop(lat, lon, name) {
  map.flyTo([lat,lon], 14, { duration:0.7 });
  setTimeout(() => {
    layers.centers.eachLayer(m => {
      if (m.getPopup && m.getPopup()?.getContent().includes(name.replace(/'/g,"\\'"))) {
        m.openPopup();
      }
    });
  }, 750);
}

function highlightZip(zip) {
  document.querySelectorAll(".zip-chip").forEach(el =>
    el.classList.toggle("highlighted", el.textContent.trim() === zip));
  layers.zips.eachLayer(l => {
    if (l.feature?.properties?.zip === zip) {
      const orig = l.options.fillOpacity || 0.06;
      l.setStyle({ fillOpacity: 0.45 });
      setTimeout(() => l.setStyle({ fillOpacity: orig }), 700);
    }
  });
}

function toggleLayer(name) {
  layerVisible[name] = !layerVisible[name];
  const btn = document.getElementById("toggle" + name.charAt(0).toUpperCase() + name.slice(1));
  if (layerVisible[name]) { map.addLayer(layers[name]); btn.classList.add("active"); }
  else { map.removeLayer(layers[name]); btn.classList.remove("active"); }
}

// ── ZIP Checkboxes ────────────────────────────────────────────────────────

function renderZipCheckboxes(zips) {
  document.getElementById("zipList").innerHTML = zips.map(z => `
    <div class="zip-item">
      <input type="checkbox" id="zchk_${z.zip}" value="${z.zip}"
        ${state.selectedZips.has(z.zip) ? "checked" : ""}
        onchange="toggleZip('${z.zip}',this.checked)"/>
      <label for="zchk_${z.zip}">${z.zip}</label>
      <span class="zip-count">${z.count}</span>
    </div>`).join("");
}

function filterZipList(query) {
  const q = query.trim();
  renderZipCheckboxes(q ? state.allZips.filter(z => z.zip.includes(q)) : state.allZips);
}

function toggleZip(zip, checked) {
  if (checked) state.selectedZips.add(zip); else state.selectedZips.delete(zip);
}

function toggleAllZips() {
  const allOn = state.selectedZips.size === state.allZips.length;
  if (allOn) state.selectedZips.clear(); else state.allZips.forEach(z => state.selectedZips.add(z.zip));
  renderZipCheckboxes(state.allZips);
}

// ── Controls ──────────────────────────────────────────────────────────────

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
}

function updateRadius(val) {
  state.thresholdMiles = parseFloat(val);
  document.getElementById("radiusLabel").textContent = parseFloat(val).toFixed(1) + " mi";
}

function setAlgo(algo) { state.algo = algo; }

// ── Export ────────────────────────────────────────────────────────────────

function exportResults() {
  if (!state.lastResult) return;
  const d = state.lastResult;
  const rows = [
    ["Name","ZIP","Address","Latitude","Longitude","Priority Score"],
    ...d.selected_stops.map(s => [s.name,s.zip,s.address,s.lat,s.lon,s.priority_score??""]),
  ];
  const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g,'""')}"`).join(",")).join("\n");
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([csv], {type:"text/csv"})),
    download: `foodreach_${d.mode}_${d.threshold_miles}mi_${d.num_stops}stops.csv`,
  });
  a.click();
}

// ── Run ───────────────────────────────────────────────────────────────────

async function runOptimization() {
  if (state.selectedZips.size === 0) { alert("Select at least one ZIP code."); return; }
  const btn = document.getElementById("runBtn");
  const loading = document.getElementById("mapLoading");
  btn.disabled = true;
  loading.classList.add("visible");
  setStatus("Running optimization…");
  clearRadiusPreview();

  try {
    const res = await fetch(`${API}/optimize`, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        mode: state.mode,
        threshold_miles: state.thresholdMiles,
        selected_zips: [...state.selectedZips],
        use_priority: state.algo === "priority",
      }),
    });
    if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
    renderResults(await res.json());
  } catch(e) {
    setStatus("⚠ " + e.message, true);
    alert("Optimization failed:\n" + e.message + "\n\nStart the backend:\n  cd backend && python3 app.py");
  } finally {
    btn.disabled = false;
    loading.classList.remove("visible");
  }
}

// ── Status ────────────────────────────────────────────────────────────────

function setStatus(msg, isError) {
  document.getElementById("headerStatus").innerHTML =
    `<span class="pulse-dot" style="${isError?"background:#e63946":""}"></span> ${msg}`;
}

init();