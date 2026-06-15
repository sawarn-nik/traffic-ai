// ======================================================
// Kolkata Traffic AI — Frontend Logic
// ======================================================

// ── Map init ────────────────────────────────────────────────────────────────
const map = L.map('map', { center: [22.5726, 88.3639], zoom: 13, zoomControl: true });
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap', maxZoom: 19
}).addTo(map);

// ── Constants ────────────────────────────────────────────────────────────────
const ROUTE_PALETTE = ['#1a73e8', '#ea4335', '#fbbc04', '#34a853', '#9c27b0'];
const RISK_COLOR = {
  CLEAR: '#34a853', LOW: '#34a853',
  MODERATE: '#e37400', HIGH: '#c5221f', CRITICAL: '#7c4dff'
};
const MODE_COLOR = {
  drive: '#1a73e8', walk: '#34a853', bike: '#e37400', metro: '#7c4dff'
};
const MODE_LABEL = {
  drive: '🚗 Drive', walk: '🚶 Walk', bike: '🚲 Bike', metro: '🚇 Metro'
};

// Disruption zone colors by severity
const ZONE_COLOR = {
  high:   { fill: '#c5221f', stroke: '#8b0000' },
  medium: { fill: '#e37400', stroke: '#b35900' },
  low:    { fill: '#fbbc04', stroke: '#c49800' },
};
const ZONE_RADIUS = { high: 420, medium: 320, low: 220 };  // metres

// ── State ────────────────────────────────────────────────────────────────────
let routeLayers     = [];
let pinLayers       = [];
let markerLayers    = [];
let zoneLayers      = [];   // disruption area zones
let overlayLayers   = [];          // metro line/station overlay
let currentRoutes   = [];
let activeIdx       = 0;
let currentMode     = 'drive';
let disruptionsLoaded   = false;
let lastDisruptionData  = null;

// ── Mode selector ────────────────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });

  // Show/hide metro overlay toggle with legend
  if (mode === 'metro') {
    loadMetroOverlay();
  } else {
    clearOverlay();
    document.getElementById('map-legend').classList.remove('visible');
  }
}

// ── Load locations ───────────────────────────────────────────────────────────
async function loadLocations() {
  try {
    const data = await (await fetch('/api/locations')).json();
    ['src-sel', 'dst-sel'].forEach(id => {
      const sel = document.getElementById(id);
      data.locations.forEach(loc => sel.appendChild(new Option(loc.name, loc.name)));
    });
  } catch { toast('Unable to load locations'); }
}

function swapLocations() {
  const s = document.getElementById('src-sel');
  const d = document.getElementById('dst-sel');
  [s.value, d.value] = [d.value, s.value];
}

// ── Metro overlay ────────────────────────────────────────────────────────────
async function loadMetroOverlay() {
  clearOverlay();
  try {
    const data = await (await fetch('/api/metro-overlay')).json();
    drawMetroOverlay(data);
    document.getElementById('map-legend').classList.add('visible');
  } catch (e) {
    console.warn('Metro overlay failed:', e);
  }
}

function drawMetroOverlay(geojson) {
  clearOverlay();
  geojson.features.forEach(f => {
    if (f.geometry.type === 'LineString') {
      const color = f.properties.color || '#9c27b0';
      const layer = L.geoJSON(f, {
        style: { color, weight: 4, opacity: 0.8, dashArray: null }
      }).addTo(map);
      layer.bindTooltip(f.properties.name, { permanent: false });
      overlayLayers.push(layer);
    } else if (f.geometry.type === 'Point') {
      const [lon, lat] = f.geometry.coordinates;
      const color = f.properties.color || '#9c27b0';
      const mk = L.circleMarker([lat, lon], {
        radius: 5, color: '#fff', weight: 1.5,
        fillColor: color, fillOpacity: 1,
      }).addTo(map);
      mk.bindPopup(
        `<b>🚇 ${f.properties.name}</b><br>` +
        `<span style="color:${color}">${f.properties.line === 'blue' ? 'Blue Line' : 'Green Line'}</span>`
      );
      overlayLayers.push(mk);
    }
  });
}

function clearOverlay() {
  overlayLayers.forEach(l => map.removeLayer(l));
  overlayLayers = [];
}

// ── Main entry ───────────────────────────────────────────────────────────────
async function go() {
  const src = document.getElementById('src-sel').value;
  const dst = document.getElementById('dst-sel').value;
  if (!src || !dst) { toast('Select source and destination'); return; }
  if (src === dst)  { toast('Source and destination cannot be the same'); return; }

  setBtn(true, 'Loading…');
  setStatus(`Computing ${currentMode} routes…`);
  clearMap();
  disruptionsLoaded  = false;
  lastDisruptionData = null;

  // Keep metro overlay visible while routing
  if (currentMode === 'metro') loadMetroOverlay();

  renderLoading(src, dst, currentMode);

  // ── Step 1: routes ───────────────────────────────────────────────────────
  let routeData;
  try {
    const res = await fetch('/api/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, destination: dst, mode: currentMode }),
    });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Routing failed'); }
    routeData = await res.json();
  } catch (e) {
    toast(e.message); setBtn(false, 'Get Routes'); renderError(e.message); return;
  }

  currentRoutes = routeData.routes;
  activeIdx     = Math.max(0, currentRoutes.findIndex(r => r.is_best));

  drawRoutes(routeData);
  renderPanel(currentRoutes, [], false, null, src, dst);
  setBtn(false, 'Get Routes');

  // Metro: no disruption analysis needed — show journey detail immediately
  if (currentMode === 'metro') {
    setStatus(`${src} → ${dst} · Metro route`);
    return;
  }

  // ── Step 2: disruptions (drive/walk/bike) ────────────────────────────────
  setStatus('Fetching disruptions…');
  try {
    const res = await fetch('/api/disruptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: src, destination: dst, mode: currentMode,
        road_names: routeData.all_road_names || [],
        routes:     routeData.routes,
      }),
    });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Disruption fetch failed'); }
    const data = await res.json();

    currentRoutes      = data.routes || currentRoutes;
    activeIdx          = Math.max(0, currentRoutes.findIndex(r => r.is_best));
    lastDisruptionData = data;
    disruptionsLoaded  = true;

    updateRouteColors(currentRoutes);
    drawMarkers(data.markers || []);
    renderPanel(currentRoutes, data.markers || [], true, data.city_weather, src, dst);
    setStatus(`${src} → ${dst} · ${data.recent_events || 0} disruptions`);
  } catch (e) {
    toast('Disruption analysis failed: ' + e.message);
    setStatus(`${src} → ${dst} · Routes shown`);
  }
}

// ── Map drawing ──────────────────────────────────────────────────────────────
function drawRoutes(data) {
  // Clear only route/pin layers — keep overlay
  routeLayers.forEach(l => map.removeLayer(l));
  pinLayers.forEach(l => map.removeLayer(l));
  markerLayers.forEach(l => map.removeLayer(l));
  routeLayers = []; pinLayers = []; markerLayers = [];

  const mode = data.mode || currentMode;

  data.routes.forEach((route, i) => {
    const isActive = i === activeIdx;
    const color    = route.risk_color || MODE_COLOR[mode] || ROUTE_PALETTE[i % 5];

    // Metro route: dashed purple to distinguish from road layers
    const dash = (mode === 'metro') ? '6 4' : (isActive ? null : '8 5');
    const w    = isActive ? 7 : 4;
    const op   = isActive ? 1 : 0.45;

    const layer = L.geoJSON(route.geojson, {
      style: { color, weight: w, opacity: op, dashArray: dash, lineJoin: 'round', lineCap: 'round' }
    }).addTo(map);

    layer.on('click', () => selectRoute(i));
    layer.bindTooltip(
      `<b>${route.label}</b><br>${route.distance_km} km · ${route.travel_time_min} min`,
      { sticky: true }
    );
    routeLayers.push(layer);
  });

  const sc = data.src_coords, dc = data.dst_coords;
  if (sc) pinLayers.push(L.marker([sc[0], sc[1]], { icon: pin('🟢') }).addTo(map).bindPopup(`<b>Start</b><br>${data.source}`));
  if (dc) pinLayers.push(L.marker([dc[0], dc[1]], { icon: pin('🔴') }).addTo(map).bindPopup(`<b>End</b><br>${data.destination}`));

  if (routeLayers[activeIdx]) {
    map.fitBounds(routeLayers[activeIdx].getBounds(), { padding: [50, 50] });
    routeLayers[activeIdx].bringToFront();
  }
}

function updateRouteColors(routes) {
  routes.forEach((r, i) => {
    if (!routeLayers[i]) return;
    const isActive = i === activeIdx;
    routeLayers[i].setStyle({
      color:     r.risk_color || MODE_COLOR[currentMode] || ROUTE_PALETTE[i % 5],
      weight:    isActive ? 7 : 4,
      opacity:   isActive ? 1 : 0.4,
      dashArray: isActive ? null : '8 5',
    });
    if (isActive) routeLayers[i].bringToFront();
  });
}

function drawMarkers(markers) {
  markerLayers.forEach(l => map.removeLayer(l));
  zoneLayers.forEach(l => map.removeLayer(l));
  markerLayers = [];
  zoneLayers   = [];

  // ── Group markers by severity for zone drawing ────────────────────────────
  const withCoords = markers.filter(m => m.lat && m.lon);

  // Draw area zones first (underneath markers)
  withCoords.forEach(m => {
    const sev   = m.severity || 'low';
    const zc    = ZONE_COLOR[sev] || ZONE_COLOR.low;
    const zr    = ZONE_RADIUS[sev] || 220;

    // Outer glow circle (large, very transparent)
    const glow = L.circle([m.lat, m.lon], {
      radius:      zr * 2.2,
      color:       zc.fill,
      weight:      0,
      fillColor:   zc.fill,
      fillOpacity: 0.06,
      interactive: false,
    }).addTo(map);
    zoneLayers.push(glow);

    // Main zone circle
    const zone = L.circle([m.lat, m.lon], {
      radius:      zr,
      color:       zc.stroke,
      weight:      1.2,
      opacity:     0.5,
      fillColor:   zc.fill,
      fillOpacity: 0.18,
      dashArray:   sev === 'high' ? null : '4 3',
    }).addTo(map);

    zone.bindTooltip(
      `<b style="color:${zc.fill}">${sev.toUpperCase()} — ${m.event_type.replace(/_/g,' ')}</b><br>` +
      `📍 ${m.location}`,
      { sticky: true, opacity: 0.95 }
    );
    zoneLayers.push(zone);
  });

  // Draw point markers on top of zones
  withCoords.forEach(m => {
    const sev  = m.severity || 'low';
    const zc   = ZONE_COLOR[sev] || ZONE_COLOR.low;
    const icon = { accident:'💥', congestion:'🚗', road_closure:'🚧',
                   construction:'🏗️', protest:'✊', weather:'🌧️',
                   waterlogging:'💧', vip_movement:'🚨', metro_disruption:'🚇',
                   train_delay:'🚂', transport_strike:'✋', diversion:'↪️' };
    const emoji = icon[m.event_type] || '⚠️';

    // Pulse ring for high severity
    if (sev === 'high') {
      const pulse = L.circleMarker([m.lat, m.lon], {
        radius: 14, color: zc.fill, weight: 2,
        fillColor: 'transparent', fillOpacity: 0, opacity: 0.4,
        className: 'pulse-ring',
      }).addTo(map);
      zoneLayers.push(pulse);
    }

    // Emoji icon marker
    const mk = L.marker([m.lat, m.lon], {
      icon: L.divIcon({
        html: `
          <div style="
            background:${zc.fill};
            border:2px solid ${zc.stroke};
            border-radius:50%;
            width:28px;height:28px;
            display:flex;align-items:center;justify-content:center;
            font-size:14px;
            box-shadow:0 2px 6px rgba(0,0,0,0.35);
            cursor:pointer;
          ">${emoji}</div>`,
        className: '',
        iconSize:   [28, 28],
        iconAnchor: [14, 14],
      }),
    }).addTo(map);

    const srcLabel = m.source === 'tomtom_traffic' ? '📡 TomTom Live'
                   : m.source === 'newsapi'         ? '📰 NewsAPI'
                   :                                  '📡 RSS';
    const dur = m.duration ? ` · ${m.duration}` : '';
    const urlLink = m.tomtom_url
      ? `<br><a href="${m.tomtom_url}" target="_blank" style="font-size:10px;color:#1a73e8">View on TomTom ↗</a>`
      : '';

    mk.bindPopup(`
      <div style="min-width:180px">
        <div style="font-weight:700;color:${zc.fill};margin-bottom:4px">
          ${emoji} ${m.event_type.replace(/_/g,' ').toUpperCase()}
          ${m.is_future ? ' <span style="background:#e8f0fe;color:#1a73e8;padding:1px 5px;border-radius:8px;font-size:10px">Upcoming</span>' : ''}
        </div>
        <div style="font-size:12px;margin-bottom:3px">📍 <b>${m.location}</b></div>
        <div style="font-size:12px;color:#3c4043;margin-bottom:5px">${m.reason}</div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="background:${zc.fill}22;color:${zc.fill};padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600">
            ${sev.toUpperCase()}
          </span>
          <span style="font-size:10px;color:#5f6368">${m.age_label}${dur}</span>
        </div>
        <div style="font-size:10px;color:#5f6368;margin-top:4px">${srcLabel}${urlLink}</div>
      </div>
    `, { maxWidth: 260 });

    markerLayers.push(mk);
  });

  // ── Draw disruption zone legend ───────────────────────────────────────────
  _updateZoneLegend(withCoords);
}

// ── Panel rendering ───────────────────────────────────────────────────────────
function renderLoading(src, dst, mode) {
  const modeLabel = MODE_LABEL[mode] || mode;
  document.getElementById('panel').innerHTML = `
    <div class="sec-lbl">${modeLabel} Routes</div>
    <div class="loading-row">
      <div class="spinner"></div>
      <span>Finding ${modeLabel.toLowerCase()} routes from <strong>${src}</strong> to <strong>${dst}</strong>…</span>
    </div>`;
}

function renderError(msg) {
  document.getElementById('panel').innerHTML = `
    <div class="empty-state"><div class="icon">⚠️</div><p>${msg}</p></div>`;
}

function renderPanel(routes, markers, ready, weather, src, dst) {
  const mode  = currentMode;
  const mLabel = MODE_LABEL[mode] || mode;

  let html = '';
  const note = (ready || mode === 'metro')
    ? ''
    : ' <span style="font-size:10px;font-weight:400;text-transform:none;letter-spacing:0;color:#9aa0a6">— analysing…</span>';

  html += `<div class="sec-lbl">${mLabel} Routes (${routes.length})${note}</div>`;

  routes.forEach((r, i) => {
    html += buildRouteCard(r, i, ready, markers, mode);
  });

  // Weather banner — only relevant for drive/bike (not metro/walk)
  if (ready && weather && (mode === 'drive' || mode === 'bike')) {
    html += buildWeatherBanner(weather);
  }

  // Disruption loading row
  if (!ready && mode !== 'metro') {
    html += `
    <div class="divider"></div>
    <div class="loading-row">
      <div class="spinner"></div>
      <span>Fetching TomTom, news &amp; running AI analysis…</span>
    </div>`;
  }

  document.getElementById('panel').innerHTML = html;
}

// ── Route card ───────────────────────────────────────────────────────────────
function buildRouteCard(r, i, ready, markers, mode) {
  const isActive  = i === activeIdx;
  const isBest    = !!r.is_best;
  const riskLevel = r.risk_level || '';
  const riskColor = RISK_COLOR[riskLevel] || '#80868b';
  const evtCount  = r.event_count || 0;
  const modeColor = MODE_COLOR[mode] || '#1a73e8';

  // Event count strip (drive/bike only)
  let evtClass = '', evtIcon = '', evtText = '';
  if (mode === 'metro' || mode === 'walk') {
    evtClass = 'ok'; evtIcon = '✓';
    evtText  = mode === 'metro' ? 'Metro route' : 'Walking route';
  } else if (!ready) {
    evtIcon = '⏳'; evtText = 'Analysing…';
  } else if (evtCount === 0) {
    evtClass = 'ok'; evtIcon = '✓'; evtText = 'No disruptions';
  } else if (riskLevel === 'HIGH' || riskLevel === 'CRITICAL') {
    const specific = r.route_specific_events || 0;
    const area     = r.area_wide_events || 0;
    evtClass = 'critical'; evtIcon = '⛔';
    evtText  = specific > 0
      ? `${specific} on route · ${area} area-wide`
      : `${evtCount} disruption${evtCount > 1 ? 's' : ''}`;
  } else {
    const specific = r.route_specific_events || 0;
    const area     = r.area_wide_events || 0;
    evtClass = 'warn'; evtIcon = '⚠';
    evtText  = specific > 0
      ? `${specific} on route · ${area} area-wide`
      : `${evtCount} disruption${evtCount > 1 ? 's' : ''}`;
  }

  // Subtitle
  let subtitle = '';
  if (mode === 'metro' && r.segments) {
    const metro = r.segments.find(s => s.type === 'metro');
    subtitle = metro ? `${metro.from} → ${metro.to}` : 'Metro + Walk';
  } else {
    subtitle = 'via ' + ((r.road_names || []).slice(0, 2).join(', ') || 'city roads');
  }

  const roadsText = (r.road_names || []).slice(0, 4).join(' · ') || '—';

  let html = `
  <div class="route-card ${isActive ? 'active' : ''} ${isBest ? 'is-best' : ''}"
       id="rc-${i}" onclick="selectRoute(${i})">

    <div class="rc-top">
      <div class="rc-num" style="${isActive ? `background:${modeColor}` : ''}">${i + 1}</div>
      <div class="rc-title">
        <div class="rc-label">${r.label}</div>
        <div class="rc-subtitle">${subtitle}</div>
      </div>
      ${isBest ? '<div class="best-badge">Best</div>' : ''}
      ${(ready && riskLevel && mode !== 'metro')
        ? `<div class="risk-pill" style="background:${riskColor}18;color:${riskColor}">${riskLevel}</div>`
        : ''}
    </div>

    <div class="rc-stats">
      <div class="stat-chip">${r.travel_time_min}<span class="lbl"> min</span></div>
      <div class="stat-chip">${r.distance_km}<span class="lbl"> km</span></div>
      ${(ready && riskLevel && mode !== 'metro')
        ? `<div class="stat-chip" style="color:${riskColor}">${r.risk_score || 0}<span class="lbl" style="color:${riskColor}99"> risk</span></div>`
        : ''}
    </div>

    ${mode !== 'metro' ? `<div class="rc-roads">${roadsText}</div>` : ''}
    <div class="rc-events ${evtClass}">${evtIcon} ${evtText}</div>`;

  // Expanded detail for the active card
  if (isActive) {
    if (mode === 'metro') {
      html += buildMetroJourney(r);
    } else {
      html += buildExpandedDetail(r, ready);
    }
  }

  html += '</div>';
  return html;
}

// ── Metro journey breakdown ───────────────────────────────────────────────────
function buildMetroJourney(r) {
  const segments = r.segments || [];
  if (segments.length === 0) {
    // Fallback: just show station list
    return buildExpandedDetail(r, true);
  }

  let html = '<div class="metro-journey">';
  html += '<div class="expand-sec">Journey Breakdown</div>';

  const isLast = (i) => i === segments.length - 1;

  segments.forEach((seg, i) => {
    const isMetro = seg.type === 'metro';
    const icon = isMetro ? '🚇' : (currentMode === 'bike' ? '🚲' : '🚶');
    const lineClass = isMetro
      ? `<span class="metro-line-pill ${seg.line || 'blue'}">${(seg.line || 'blue').toUpperCase()} LINE</span>`
      : '';

    let detail = '';
    if (isMetro && seg.stations) {
      const stops = seg.stations;
      const count = seg.num_stops || stops.length - 1;
      detail = `${stops[0]} → ${stops[stops.length - 1]} · ${count} stop${count !== 1 ? 's' : ''}`;
      if (seg.stations.length > 2) {
        const midStops = stops.slice(1, -1).join(', ');
        detail += `<br><small style="color:#9aa0a6">${midStops}</small>`;
      }
    } else {
      detail = `${seg.from} → ${seg.to} · ${seg.distance_km} km`;
    }

    html += `
    <div class="journey-seg">
      <div class="seg-track">
        <div class="seg-icon ${seg.type}">${icon}</div>
        ${!isLast(i) ? `<div class="seg-connector ${seg.type}"></div>` : ''}
      </div>
      <div class="seg-body">
        <div class="seg-title">${isMetro ? 'Metro' : 'Walk'} ${lineClass}</div>
        <div class="seg-detail">${detail}</div>
        <div class="seg-time-chip">${seg.time_min} min · ${seg.distance_km} km</div>
      </div>
    </div>`;
  });

  // Interchange note
  if (r.interchange) {
    html += `
    <div class="metro-note-banner">
      🔄 Interchange at Esplanade — change between Blue and Green Line
    </div>`;
  }

  // Metro note
  if (r.metro_note) {
    html += `<div class="metro-note-banner">${r.metro_note}</div>`;
  }

  html += '</div>';
  return html;
}

// ── Expanded road + disruption detail ────────────────────────────────────────
function buildExpandedDetail(r, ready) {
  let html = '<div class="card-expand">';

  const allRoads = r.road_names || [];
  if (allRoads.length > 0) {
    html += `<div class="expand-sec">Road Segments (${allRoads.length})</div>`;
    html += '<div class="road-node-list">';
    allRoads.forEach((road, idx) => {
      const first = idx === 0, last = idx === allRoads.length - 1;
      const dot   = first ? 'node-dot-start' : last ? 'node-dot-end' : 'node-dot-mid';
      html += `
      <div class="road-node-row">
        <div class="node-track">
          <div class="node-dot ${dot}"></div>
          ${!last ? '<div class="node-line"></div>' : ''}
        </div>
        <div class="node-label">${road}</div>
      </div>`;
    });
    html += '</div>';
  }

  if (ready) {
    const allActive = (r.matched_events || []).filter(e => !e.is_future_event);
    const future    = (r.matched_events || []).filter(e =>  e.is_future_event);

    // Split into route-specific and area-wide
    const specific  = allActive.filter(e => e.route_specific);
    const areaWide  = allActive.filter(e => !e.route_specific);

    if (allActive.length === 0) {
      html += '<div class="expand-sec">Disruptions on this Route (0)</div>';
      html += '<div class="expand-clear">✓ No active disruptions</div>';
    } else {
      // Route-specific disruptions
      if (specific.length > 0) {
        html += `
        <div class="expand-sec">
          On This Route
          <span class="sec-badge specific">${specific.length}</span>
        </div>`;
        specific.forEach(ev => { html += buildEventCard(ev); });
      }

      // Area-wide disruptions (collapsible)
      if (areaWide.length > 0) {
        const areaId = `area-${r.id || Math.random()}`;
        html += `
        <div class="expand-sec area-sec" onclick="toggleAreaEvents('${areaId}')">
          Area-wide (affect all routes)
          <span class="sec-badge area">${areaWide.length}</span>
          <span class="area-toggle" id="tog-${areaId}">▼</span>
        </div>
        <div id="${areaId}" class="area-events-list">`;
        areaWide.forEach(ev => { html += buildEventCard(ev, false, true); });
        html += '</div>';
      }
    }

    if (future.length > 0) {
      html += `<div class="expand-sec">Upcoming (${future.length})</div>`;
      future.forEach(ev => { html += buildEventCard(ev, true); });
    }
  } else {
    html += `
    <div class="loading-row" style="padding:8px 0 4px">
      <div class="spinner"></div>
      <span style="font-size:12px">Analysing disruptions…</span>
    </div>`;
  }

  html += '</div>';
  return html;
}

function toggleAreaEvents(id) {
  const el  = document.getElementById(id);
  const tog = document.getElementById('tog-' + id);
  if (!el) return;
  const hidden = el.style.display === 'none' || el.style.display === '';
  el.style.display   = hidden ? 'block' : 'none';
  if (tog) tog.textContent = hidden ? '▲' : '▼';
}

function buildEventCard(ev, isFuture = false, isAreaWide = false) {
  const isLive = ev.source === 'tomtom_traffic';
  const dur    = ev.impact_duration_label ? ` · ${ev.impact_duration_label}` : '';
  const src    = isLive ? '📡 TomTom Live' : ev.source === 'newsapi' ? '📰 NewsAPI' : '📡 RSS';
  const ftag   = isFuture  ? '<span class="future-tag">Upcoming</span>' : '';
  const atag   = isAreaWide ? '<span class="area-tag">Area-wide</span>'  : '';
  const corrTag = ev.severity_corrected ? '<span class="hgnn-tag">HGNN ✓</span>' : '';
  return `
  <div class="ev-item ${ev.severity} ${isAreaWide ? 'area-wide-ev' : ''}">
    <div class="ev-head">
      <span class="ev-type" style="color:${ev.color || '#5f6368'}">${ev.event_type.replace(/_/g, ' ')}${ftag}${atag}${corrTag}</span>
      <span class="ev-age">${ev.age_label || ''}</span>
    </div>
    <div class="ev-loc">📍 ${ev.location}</div>
    <div class="ev-reason">${ev.reason}</div>
    <div class="ev-meta">
      <span class="${isLive ? 'live' : ''}">${src}</span>
      ${dur ? `<span>${dur}</span>` : ''}
    </div>
  </div>`;
}

// ── Weather banner ────────────────────────────────────────────────────────────
function buildWeatherBanner(weather) {
  if (!weather || !weather.success) return '';
  const sev    = (weather.severity || 'unknown').toLowerCase();
  const wsi    = weather.avg_wsi != null ? weather.avg_wsi.toFixed(2) : 'N/A';
  const score  = weather.score || 0;
  const raw    = weather.raw || {};
  const temp   = raw.temp   != null ? `${raw.temp}°C` : '';
  const cond   = raw.condition || '';
  const humid  = raw.humidity  != null ? `${raw.humidity}% humidity` : '';
  const wind   = raw.wind_speed != null ? `${raw.wind_speed} m/s wind` : '';
  const rain   = raw.rain_1h > 0 ? `${raw.rain_1h} mm/h rain` : '';
  const icon   = sev === 'high' ? '🌧️' : sev === 'medium' ? '🌦️'
               : cond === 'Thunderstorm' ? '⛈️' : cond === 'Fog' || cond === 'Haze' ? '🌫️' : '☀️';
  const detail = [temp, cond, rain, wind, humid].filter(Boolean).join(' · ');
  return `
  <div class="divider"></div>
  <div class="weather-banner">
    <div class="weather-icon">${icon}</div>
    <div class="weather-body">
      <div class="weather-title">City-wide Weather · Kolkata</div>
      <div class="weather-detail">${detail || 'Conditions normal'}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:5px;flex-wrap:wrap">
        <div class="weather-sev ${sev}">${sev.toUpperCase()}</div>
        <div style="font-size:11px;color:#5f6368">WSI ${wsi} · +${score} pts on all routes</div>
      </div>
      <div class="weather-note">City-wide — applied equally to every route</div>
    </div>
  </div>`;
}

// ── Route selection ──────────────────────────────────────────────────────────
function selectRoute(i) {
  activeIdx = i;
  updateRouteColors(currentRoutes);
  if (routeLayers[i]) {
    map.fitBounds(routeLayers[i].getBounds(), { padding: [50, 50] });
    routeLayers[i].bringToFront();
  }
  renderPanel(
    currentRoutes,
    lastDisruptionData?.markers || [],
    disruptionsLoaded,
    lastDisruptionData?.city_weather || null,
    document.getElementById('src-sel').value,
    document.getElementById('dst-sel').value,
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function clearMap() {
  routeLayers.forEach(l => map.removeLayer(l));
  pinLayers.forEach(l => map.removeLayer(l));
  markerLayers.forEach(l => map.removeLayer(l));
  zoneLayers.forEach(l => map.removeLayer(l));
  routeLayers = []; pinLayers = []; markerLayers = []; zoneLayers = [];
  // Remove zone legend
  const leg = document.getElementById('zone-legend');
  if (leg) leg.remove();
}

function pin(emoji) {
  return L.divIcon({
    html: `<div style="font-size:22px;line-height:1">${emoji}</div>`,
    className: '', iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

function setBtn(disabled, text) {
  const b = document.getElementById('btn-go');
  b.disabled = disabled; b.innerText = text;
}

function setStatus(text) {
  document.getElementById('status-l').innerText = text;
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.innerText = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3500);
}

// ── Disruption zone legend ────────────────────────────────────────────────────
function _updateZoneLegend(markers) {
  // Remove old legend
  const old = document.getElementById('zone-legend');
  if (old) old.remove();

  if (!markers || markers.length === 0) return;

  const counts = { high: 0, medium: 0, low: 0 };
  markers.forEach(m => {
    const s = m.severity || 'low';
    if (counts[s] !== undefined) counts[s]++;
  });

  const rows = Object.entries(counts)
    .filter(([, c]) => c > 0)
    .map(([sev, cnt]) => {
      const zc = ZONE_COLOR[sev] || ZONE_COLOR.low;
      return `
      <div class="zleg-row">
        <div class="zleg-swatch" style="background:${zc.fill};border:1.5px solid ${zc.stroke}"></div>
        <span>${sev.charAt(0).toUpperCase()+sev.slice(1)}</span>
        <span class="zleg-count">${cnt}</span>
      </div>`;
    }).join('');

  const leg = document.createElement('div');
  leg.id        = 'zone-legend';
  leg.className = 'zone-legend';
  leg.innerHTML = `
    <div class="zleg-title">Disruption Zones</div>
    ${rows}
    <div class="zleg-note">Radius = severity</div>
  `;
  document.body.appendChild(leg);
}

// ── Boot ─────────────────────────────────────────────────────────────────────
loadLocations();
