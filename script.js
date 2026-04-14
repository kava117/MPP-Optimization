const MAP_CENTER = [28.5383, -81.3792]; // Orlando
const MAP_ZOOM_DEFAULT = 11;

// Global State
let map;
let zipLayerGroup = L.layerGroup();
let candidateLayerGroup = L.layerGroup();
let optimalLayerGroup = L.layerGroup();

let zipData = null;
let candidateData = null;
let optimalData = null;

let currentMode = 'walking';

const DOM = {
    valOptimalStops: document.getElementById('val-optimal-stops'),
    valZipsCovered: document.getElementById('val-zips-covered'),
    valZipsTotal: document.getElementById('val-zips-total'),
    valCoverageRate: document.getElementById('val-coverage-rate'),
    scenarios: document.querySelectorAll('.btn-scenario'),
    layers: {
        zips: document.getElementById('layer-zips'),
        candidates: document.getElementById('layer-candidates'),
        optimal: document.getElementById('layer-optimal')
    },
    loading: document.getElementById('map-loading'),
    error: document.getElementById('map-error')
};

async function init() {
    initMap();
    setupEventListeners();
    await loadBaseData();
    await updateScenario(currentMode);
}

function initMap() {
    map = L.map('map', {
        zoomControl: false // Create custom positioning if needed
    }).setView(MAP_CENTER, MAP_ZOOM_DEFAULT);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Premium light basemap
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 20
    }).addTo(map);

    zipLayerGroup.addTo(map);
    candidateLayerGroup.addTo(map);
    optimalLayerGroup.addTo(map);
}

function setupEventListeners() {
    // Escenarios
    DOM.scenarios.forEach(btn => {
        btn.addEventListener('click', (e) => {
            DOM.scenarios.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            const mode = e.target.getAttribute('data-mode');
            if (mode !== currentMode) {
                currentMode = mode;
                updateScenario(mode);
            }
        });
    });

    // Layer Toggles
    DOM.layers.zips.addEventListener('change', (e) => {
        e.target.checked ? map.addLayer(zipLayerGroup) : map.removeLayer(zipLayerGroup);
    });
    DOM.layers.candidates.addEventListener('change', (e) => {
        e.target.checked ? map.addLayer(candidateLayerGroup) : map.removeLayer(candidateLayerGroup);
    });
    DOM.layers.optimal.addEventListener('change', (e) => {
        e.target.checked ? map.addLayer(optimalLayerGroup) : map.removeLayer(optimalLayerGroup);
        renderZips(); // Highlight covered zips when optimal is toggled
    });
}

function showLoading(show) {
    if (show) DOM.loading.classList.remove('hidden');
    else DOM.loading.classList.add('hidden');
}

function showError(msg) {
    if (msg) {
        DOM.error.textContent = msg;
        DOM.error.classList.remove('hidden');
        setTimeout(() => DOM.error.classList.add('hidden'), 5000);
    }
}

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed loading ${url}`);
    return await res.json();
}

async function loadBaseData() {
    showLoading(true);
    try {
        // We load parallel requests
        [zipData, candidateData] = await Promise.all([
            fetchJSON('data/zipcodes.geojson').catch(() => null),
            fetchJSON('data/candidate_stops.geojson').catch(() => null)
        ]);

        if (zipData) {
            DOM.valZipsTotal.textContent = zipData.features.length;
            renderZips(); // will be rendered fully in renderZips with highlighting
        }

        if (candidateData) {
            renderCandidates();
        }
    } catch (err) {
        console.error(err);
        showError("Base geographic data could not be loaded.");
    }
    showLoading(false);
}

async function updateScenario(mode) {
    showLoading(true);
    try {
        optimalData = await fetchJSON(`data/optimal_stops_${mode}.json`);
        renderOptimalAndCoverage();
        renderZips(); // Recalculate zip highlighting based on new stops
        updateDashboard();
    } catch (err) {
        console.error(err);
        showError(`Scenario data for ${mode} not found. Ensure optimal_stops_${mode}.json exists.`);
        optimalLayerGroup.clearLayers();
        optimalData = null;
        updateDashboard();
        renderZips();
    }
    showLoading(false);
}

// Rendering Methods

function renderCandidates() {
    candidateLayerGroup.clearLayers();
    if (!candidateData) return;

    L.geoJSON(candidateData, {
        pointToLayer: function (feature, latlng) {
            return L.circleMarker(latlng, {
                radius: 4,
                fillColor: "var(--color-candidate)",
                color: "#FFFFFF",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.8
            });
        },
        onEachFeature: function(feature, layer) {
            layer.bindPopup(`
                <div class="popup-title">${feature.properties.name || 'Candidate Stop'}</div>
                <div class="popup-property">ID: <span>${feature.properties.id || feature.properties.name || 'N/A'}</span></div>
            `);
        }
    }).addTo(candidateLayerGroup);
}

function renderOptimalAndCoverage() {
    optimalLayerGroup.clearLayers();
    if (!optimalData || !candidateData) return;

    const optIds = optimalData.optimal_stops || [];
    
    // Find matching candidate features
    const optFeatures = candidateData.features.filter(f => optIds.includes(f.properties.id));

    optFeatures.forEach(feature => {
        const coords = feature.geometry.coordinates; // [lng, lat]
        const latlng = [coords[1], coords[0]];

        // 1. Draw solid marker
        const marker = L.circleMarker(latlng, {
            radius: 8,
            fillColor: "var(--color-optimal)",
            color: "#FFFFFF",
            weight: 2,
            fillOpacity: 1
        });
        marker.bindPopup(`
            <div class="popup-title">${feature.properties.name || 'Optimal Stop'}</div>
            <div class="popup-property">Status: <span>Selected</span></div>
        `);
        marker.addTo(optimalLayerGroup);

        // 2. Draw coverage radius circle (~3km for demo purposes, can be adjusted or read from data)
        L.circle(latlng, {
            radius: 3000,
            fillColor: "var(--color-coverage)",
            color: "var(--color-optimal)",
            weight: 1,
            fillOpacity: 0.2,
            dashArray: "5, 5"
        }).addTo(optimalLayerGroup);
    });
    
    // Fit bounds subtly to the optimal ones
    if(optFeatures.length > 0) {
        const bounds = L.latLngBounds(optFeatures.map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0]]));
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 13, animate: true, duration: 1 });
    }
}

// A simple approximation to check if string contains substring or using bounding box.
// In a real app we would use Turf.js for intersection, but we stick to vanilla.
function isZipCovered(zipBounds) {
    if (!optimalData || !candidateData || !DOM.layers.optimal.checked) return false;
    const optIds = optimalData.optimal_stops || [];
    const optFeatures = candidateData.features.filter(f => optIds.includes(f.properties.id));
    
    const zCenter = zipBounds.getCenter();
    for(let i=0; i<optFeatures.length; i++) {
        const coords = optFeatures[i].geometry.coordinates;
        const oLatLng = L.latLng(coords[1], coords[0]);
        const dist = zCenter.distanceTo(oLatLng);
        if (dist <= 6000) return true; // threshold distance for highlighting
    }
    return false;
}

function renderZips() {
    zipLayerGroup.clearLayers();
    if (!zipData) return;
    
    let coveredCount = 0;

    L.geoJSON(zipData, {
        style: function (feature) {
            // Check if feature is 'covered'. 
            // Since we need to calculate it inside here, we rely on a rough bounding box check
            // BUT bounds require the layer to be instantiated first to get bounds.
            // As a simple shortcut for this render: we will style it slightly transparent blue
            return {
                color: "var(--color-zip)",
                weight: 1,
                fillColor: "var(--color-zip)",
                fillOpacity: 0.05
            };
        },
        onEachFeature: function(feature, layer) {
            // Once layer is instantiated, we can check its bounds
            setTimeout(() => {
                const covered = isZipCovered(layer.getBounds());
                if(covered) {
                    layer.setStyle({
                        color: "var(--color-zip-active)",
                        fillColor: "var(--color-zip-active)",
                        fillOpacity: 0.15,
                        weight: 2
                    });
                    coveredCount++;
                    DOM.valZipsCovered.textContent = coveredCount;
                }
            }, 50);

            layer.bindPopup(`
                <div class="popup-title">ZIP Code</div>
                <div class="popup-property">Zip: <span>${feature.properties.ZCTA5CE20 || feature.properties.zip || 'Unknown'}</span></div>
            `);
        }
    }).addTo(zipLayerGroup);

    DOM.valZipsCovered.textContent = 0;
}

function updateDashboard() {
    if(optimalData) {
        DOM.valOptimalStops.textContent = optimalData.optimal_stops ? optimalData.optimal_stops.length : 0;
        const rate = (optimalData.coverage * 100).toFixed(0);
        DOM.valCoverageRate.textContent = `${rate}%`;
    } else {
        DOM.valOptimalStops.textContent = '--';
        DOM.valCoverageRate.textContent = '--%';
        DOM.valZipsCovered.textContent = '--';
    }
}

// Start
document.addEventListener('DOMContentLoaded', init);
