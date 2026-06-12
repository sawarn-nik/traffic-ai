"""
multimodal.py — Mode-aware routing for Kolkata Traffic AI
==========================================================

Supports four transport modes:

  drive  — OSMnx drive network (existing graph.pkl)
  walk   — OSMnx walk network  (graph_walk.pkl, lazy-downloaded)
  bike   — OSMnx bike network  (graph_bike.pkl, lazy-downloaded)
  metro  — Simplified metro model:
             walk to nearest station → metro line → walk from station

Metro model notes:
  • Uses hardcoded Kolkata Metro Blue Line (Line 1) + Green Line (Line 2) stations
    with real lat/lon coordinates.
  • Walk legs use the OSMnx walk graph (or straight-line estimate if unavailable).
  • Metro travel speed: 35 km/h average including dwell time.
  • Walk speed: 5 km/h.
  • This is a planning estimate — no real-time GTFS feed is used.

Speed assumptions:
  drive  → 30 km/h (Kolkata city average with traffic)
  walk   → 5  km/h
  bike   → 15 km/h
  metro  → 35 km/h on metro segment + 5 km/h walk legs
"""

from __future__ import annotations

import os
import pickle
import math
from typing import Literal

import osmnx as ox

from config import GRAPH_CACHE_PATH, MAX_ROUTES, MIN_ROUTE_DIVERGENCE, MAX_CONSECUTIVE_DUPES

# ── Cache paths ───────────────────────────────────────────────────────────────
_CACHE_DIR  = os.path.dirname(GRAPH_CACHE_PATH)
_GRAPH_WALK = os.path.join(_CACHE_DIR, "graph_walk.pkl")
_GRAPH_BIKE = os.path.join(_CACHE_DIR, "graph_bike.pkl")

TransportMode = Literal["drive", "walk", "bike", "metro"]

# Speed in km/h by mode (used for travel_time_min estimation)
MODE_SPEED_KMH: dict[str, float] = {
    "drive": 30.0,
    "walk":  5.0,
    "bike":  15.0,
    "metro": 35.0,  # metro segment speed
}

# ── Kolkata Metro station data ─────────────────────────────────────────────────
# Blue Line (Line 1) — Dakshineswar ↔ New Garia
# Green Line (Line 2) — Salt Lake Sector V ↔ Howrah Maidan  (partial, operational section)
# Coords: (lat, lon)

METRO_STATIONS: list[dict] = [
    # Blue Line (Line 1) — N → S
    {"id": "bl_dakshineswar",       "name": "Dakshineswar",         "lat": 22.6427, "lon": 88.3574, "line": "blue"},
    {"id": "bl_baranagar",          "name": "Baranagar Road",       "lat": 22.6360, "lon": 88.3779, "line": "blue"},
    {"id": "bl_noapara",            "name": "Noapara",              "lat": 22.6241, "lon": 88.3794, "line": "blue"},
    {"id": "bl_dumdum",             "name": "Dum Dum",              "lat": 22.6169, "lon": 88.3969, "line": "blue"},
    {"id": "bl_belgachia",          "name": "Belgachia",            "lat": 22.6085, "lon": 88.3846, "line": "blue"},
    {"id": "bl_shyambazar",         "name": "Shyambazar",           "lat": 22.5997, "lon": 88.3744, "line": "blue"},
    {"id": "bl_shobhabazar",        "name": "Shobhabazar Sutanuti", "lat": 22.5935, "lon": 88.3681, "line": "blue"},
    {"id": "bl_girish_park",        "name": "Girish Park",          "lat": 22.5882, "lon": 88.3637, "line": "blue"},
    {"id": "bl_mahatma_gandhi_rd",  "name": "Mahatma Gandhi Road",  "lat": 22.5847, "lon": 88.3600, "line": "blue"},
    {"id": "bl_central",            "name": "Central",              "lat": 22.5802, "lon": 88.3558, "line": "blue"},
    {"id": "bl_chandni_chowk",      "name": "Chandni Chowk",        "lat": 22.5741, "lon": 88.3523, "line": "blue"},
    {"id": "bl_esplanade",          "name": "Esplanade",            "lat": 22.5664, "lon": 88.3506, "line": "blue"},
    {"id": "bl_park_street",        "name": "Park Street",          "lat": 22.5546, "lon": 88.3521, "line": "blue"},
    {"id": "bl_maidan",             "name": "Maidan",               "lat": 22.5498, "lon": 88.3436, "line": "blue"},
    {"id": "bl_rabindra_sadan",     "name": "Rabindra Sadan",       "lat": 22.5438, "lon": 88.3443, "line": "blue"},
    {"id": "bl_netaji_bhavan",      "name": "Netaji Bhavan",        "lat": 22.5381, "lon": 88.3456, "line": "blue"},
    {"id": "bl_jatin_das_park",     "name": "Jatin Das Park",       "lat": 22.5322, "lon": 88.3460, "line": "blue"},
    {"id": "bl_kalighat",           "name": "Kalighat",             "lat": 22.5249, "lon": 88.3436, "line": "blue"},
    {"id": "bl_tollygunge",         "name": "Tollygunge",           "lat": 22.5143, "lon": 88.3461, "line": "blue"},
    {"id": "bl_mahanayak",          "name": "Mahanayak Uttam Kumar","lat": 22.5021, "lon": 88.3462, "line": "blue"},
    {"id": "bl_netaji",             "name": "Netaji",               "lat": 22.4921, "lon": 88.3477, "line": "blue"},
    {"id": "bl_masterda",           "name": "Masterda Surya Sen",   "lat": 22.4845, "lon": 88.3479, "line": "blue"},
    {"id": "bl_gitanjali",          "name": "Gitanjali",            "lat": 22.4773, "lon": 88.3479, "line": "blue"},
    {"id": "bl_kavi_nazrul",        "name": "Kavi Nazrul",          "lat": 22.4699, "lon": 88.3479, "line": "blue"},
    {"id": "bl_shahid_khudiram",    "name": "Shahid Khudiram",      "lat": 22.4627, "lon": 88.3481, "line": "blue"},
    {"id": "bl_kavi_subhash",       "name": "Kavi Subhash",         "lat": 22.4552, "lon": 88.3494, "line": "blue"},
    {"id": "bl_new_garia",          "name": "New Garia",            "lat": 22.4502, "lon": 88.3897, "line": "blue"},

    # Green Line (Line 2) — operational section: Salt Lake Sector V ↔ Phoolbagan
    {"id": "gl_salt_lake_sector_v", "name": "Salt Lake Sector V",   "lat": 22.5753, "lon": 88.4346, "line": "green"},
    {"id": "gl_karunamoyee",        "name": "Karunamoyee",          "lat": 22.5743, "lon": 88.4264, "line": "green"},
    {"id": "gl_central_park",       "name": "Central Park",         "lat": 22.5735, "lon": 88.4190, "line": "green"},
    {"id": "gl_city_centre",        "name": "City Centre",          "lat": 22.5724, "lon": 88.4118, "line": "green"},
    {"id": "gl_bengal_chemical",    "name": "Bengal Chemical",      "lat": 22.5715, "lon": 88.4027, "line": "green"},
    {"id": "gl_salt_lake_stadium",  "name": "Salt Lake Stadium",    "lat": 22.5701, "lon": 88.3962, "line": "green"},
    {"id": "gl_phoolbagan",         "name": "Phoolbagan",           "lat": 22.5694, "lon": 88.3893, "line": "green"},
    {"id": "gl_sealdah",            "name": "Sealdah",              "lat": 22.5679, "lon": 88.3700, "line": "green"},
    {"id": "gl_esplanade",          "name": "Esplanade (Green)",    "lat": 22.5664, "lon": 88.3506, "line": "green"},
    {"id": "gl_mahakaran",          "name": "Mahakaran",            "lat": 22.5617, "lon": 88.3433, "line": "green"},
    {"id": "gl_howrah_maidan",      "name": "Howrah Maidan",        "lat": 22.5840, "lon": 88.3283, "line": "green"},
]

# Build index by station id
_STATION_BY_ID = {s["id"]: s for s in METRO_STATIONS}

# Metro line connectivity (ordered station lists for path finding)
_BLUE_LINE = [s for s in METRO_STATIONS if s["line"] == "blue"]
_GREEN_LINE = [s for s in METRO_STATIONS if s["line"] == "green"]

LINE_COLORS = {
    "blue":  "#2196F3",
    "green": "#4CAF50",
}

# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _nearest_station(lat: float, lon: float) -> dict:
    """Return the metro station nearest to a coordinate."""
    return min(METRO_STATIONS, key=lambda s: _haversine_km(lat, lon, s["lat"], s["lon"]))


def _metro_path(src_station: dict, dst_station: dict) -> list[dict] | None:
    """
    Find the ordered list of stations between src and dst on the same line,
    including any interchange at Esplanade (Blue/Green junction).

    Returns list of station dicts in travel order, or None if unreachable.
    """
    def _on_same_line(a: dict, b: dict, line: list[dict]) -> list[dict] | None:
        ids = [s["id"] for s in line]
        if a["id"] in ids and b["id"] in ids:
            i, j = ids.index(a["id"]), ids.index(b["id"])
            if i <= j:
                return line[i:j+1]
            else:
                return list(reversed(line[j:i+1]))
        return None

    # Try direct path on blue or green
    for line in (_BLUE_LINE, _GREEN_LINE):
        path = _on_same_line(src_station, dst_station, line)
        if path:
            return path

    # Try interchange via Esplanade (where blue + green meet)
    blue_esplanade  = _STATION_BY_ID.get("bl_esplanade")
    green_esplanade = _STATION_BY_ID.get("gl_esplanade")
    if not blue_esplanade or not green_esplanade:
        return None

    # src → blue Esplanade → green Esplanade → dst
    seg1 = _on_same_line(src_station, blue_esplanade, _BLUE_LINE)
    seg2 = _on_same_line(green_esplanade, dst_station, _GREEN_LINE)
    if seg1 and seg2:
        return seg1 + seg2

    # src → green Esplanade → blue Esplanade → dst
    seg1 = _on_same_line(src_station, green_esplanade, _GREEN_LINE)
    seg2 = _on_same_line(blue_esplanade, dst_station, _BLUE_LINE)
    if seg1 and seg2:
        return seg1 + seg2

    return None


# ── Graph loaders ─────────────────────────────────────────────────────────────

_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.openstreetmap.ru/api",
]

_GRAPH_PLACES = [
    "Kolkata, West Bengal, India",
    "Bidhannagar, West Bengal, India",
    "North Dum Dum, West Bengal, India",
    "Barasat I, West Bengal, India",
    "Barasat II, West Bengal, India",
]


def _load_or_download_graph(network_type: str, cache_path: str):
    if os.path.exists(cache_path):
        print(f"  [Route] Loading cached {network_type} graph from {cache_path} ...")
        with open(cache_path, "rb") as f:
            g = pickle.load(f)
        print(f"  [Route] {network_type} graph loaded ({len(g.nodes):,} nodes)")
        return g

    print(f"  [Route] Downloading OSM {network_type} network (one-time, ~30-60s) ...")
    ox.settings.timeout = 180
    last_err = None
    for ep in _OVERPASS_ENDPOINTS:
        try:
            ox.settings.overpass_url = ep
            g = ox.graph_from_place(_GRAPH_PLACES, network_type=network_type, retain_all=False)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "wb") as f:
                pickle.dump(g, f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"  [Route] {network_type} graph cached ({len(g.nodes):,} nodes)")
            return g
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to download {network_type} graph: {last_err}")


# ── Geocoding (reuse from route_engine) ──────────────────────────────────────

def _geocode(place: str) -> tuple[float, float]:
    from routing.route_engine import _geocode_with_context
    return _geocode_with_context(place)


# ── GeoJSON builder ───────────────────────────────────────────────────────────

def _nodes_to_geojson(graph, node_list: list, label: str, distance_km: float, travel_time_min: float) -> dict:
    coords = [
        [graph.nodes[n]["x"], graph.nodes[n]["y"]]
        for n in node_list
        if "x" in graph.nodes[n] and "y" in graph.nodes[n]
    ]
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"label": label, "distance_km": distance_km, "travel_time_min": travel_time_min},
        }]
    }


def _straight_geojson(points: list[tuple[float, float]], label: str, distance_km: float, travel_time_min: float) -> dict:
    """GeoJSON from a list of (lat, lon) tuples."""
    coords = [[lon, lat] for lat, lon in points]
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"label": label, "distance_km": distance_km, "travel_time_min": travel_time_min},
        }]
    }


# ── Road-network routing (drive / walk / bike) ────────────────────────────────

def _road_routes(source: str, destination: str, network_type: str, speed_kmh: float) -> dict:
    """
    Compute multiple distinct routes on a road network graph.
    Returns the same shape as route_engine.get_multiple_routes().
    """
    from routing.route_engine import extract_road_names, _routes_are_distinct

    if network_type == "drive":
        cache_path = GRAPH_CACHE_PATH
    elif network_type == "walk":
        cache_path = _GRAPH_WALK
    else:
        cache_path = _GRAPH_BIKE

    graph = _load_or_download_graph(network_type, cache_path)

    src_coords  = _geocode(source)
    dst_coords  = _geocode(destination)

    src_node  = ox.distance.nearest_nodes(graph, X=src_coords[1],  Y=src_coords[0])
    dest_node = ox.distance.nearest_nodes(graph, X=dst_coords[1],  Y=dst_coords[0])

    PENALTY       = 5.0
    max_routes    = MAX_ROUTES
    max_attempts  = max_routes * 6

    G = graph.copy()
    routes_raw: list     = []
    seen_sets:  list     = []
    dupes = 0

    for _ in range(max_attempts):
        if len(routes_raw) >= max_routes: break
        if dupes >= MAX_CONSECUTIVE_DUPES: break

        route = ox.shortest_path(G, src_node, dest_node, weight="length")
        if route is None: break

        edge_set = frozenset(zip(route[:-1], route[1:]))
        is_new = all(_routes_are_distinct(edge_set, prev, MIN_ROUTE_DIVERGENCE) for prev in seen_sets)

        for u, v in zip(route[:-1], route[1:]):
            for k in G[u][v]:
                G[u][v][k]["length"] *= PENALTY

        if not is_new:
            dupes += 1; continue

        routes_raw.append(route)
        seen_sets.append(edge_set)
        dupes = 0

    if not routes_raw:
        raise ValueError(f"No {network_type} route found between '{source}' and '{destination}'.")

    routes_out = []
    for idx, node_list in enumerate(routes_raw):
        roads = extract_road_names(graph, node_list)
        total_m = sum(
            graph.get_edge_data(u, v, 0).get("length", 0)
            for u, v in zip(node_list[:-1], node_list[1:])
        )
        dist_km   = round(total_m / 1000, 2)
        time_min  = round((dist_km / speed_kmh) * 60)
        coords    = [(graph.nodes[n]["y"], graph.nodes[n]["x"]) for n in node_list if "y" in graph.nodes[n]]
        geojson   = _nodes_to_geojson(graph, node_list, f"Route {idx+1}", dist_km, time_min)

        routes_out.append({
            "id":              idx,
            "label":           f"Route {idx+1}",
            "road_names":      roads,
            "distance_km":     dist_km,
            "travel_time_min": time_min,
            "geojson":         geojson,
            "node_ids":        node_list,
            "coords":          coords,
            "mode":            network_type,
        })

    return {
        "source":      source,
        "destination": destination,
        "src_coords":  list(src_coords),
        "dst_coords":  list(dst_coords),
        "routes":      routes_out,
        "mode":        network_type,
    }


# ── Metro routing ─────────────────────────────────────────────────────────────

def _metro_route(source: str, destination: str) -> dict:
    """
    Build a metro route:
      Walk (source → nearest metro station)
      → Metro (station sequence along the line)
      → Walk (nearest metro station → destination)

    Returns one "route" in the same shape as _road_routes(), but with
    additional metro-specific fields:
      segments: list of {type, from, to, distance_km, time_min, stations, geojson}
      metro_stations_used: list of station names
    """
    src_coords = _geocode(source)
    dst_coords = _geocode(destination)

    src_lat, src_lon = src_coords
    dst_lat, dst_lon = dst_coords

    # Nearest stations to source and destination
    src_station = _nearest_station(src_lat, src_lon)
    dst_station = _nearest_station(dst_lat, dst_lon)

    # Walk distances
    walk_src_km = _haversine_km(src_lat, src_lon, src_station["lat"], src_station["lon"])
    walk_dst_km = _haversine_km(dst_lat, dst_lon, dst_station["lat"], dst_station["lon"])

    walk_src_min = round((walk_src_km / 5.0) * 60)
    walk_dst_min = round((walk_dst_km / 5.0) * 60)

    # Metro path between stations
    metro_path = _metro_path(src_station, dst_station)

    if metro_path is None or len(metro_path) < 2:
        # No metro path — fall back to straight walk
        total_km  = _haversine_km(src_lat, src_lon, dst_lat, dst_lon)
        total_min = round((total_km / 5.0) * 60)
        geojson   = _straight_geojson([(src_lat, src_lon), (dst_lat, dst_lon)], "Walk (no metro)", total_km, total_min)
        return {
            "source": source, "destination": destination,
            "src_coords": list(src_coords), "dst_coords": list(dst_coords),
            "mode": "metro",
            "routes": [{
                "id": 0, "label": "Walk (no metro connection)",
                "road_names": [], "distance_km": round(total_km, 2),
                "travel_time_min": total_min, "geojson": geojson,
                "coords": [(src_lat, src_lon), (dst_lat, dst_lon)],
                "mode": "metro",
                "segments": [],
                "metro_note": "No metro connection between these points. Showing walk route.",
            }],
        }

    # Compute metro distance along station sequence
    metro_km = sum(
        _haversine_km(metro_path[i]["lat"], metro_path[i]["lon"],
                      metro_path[i+1]["lat"], metro_path[i+1]["lon"])
        for i in range(len(metro_path) - 1)
    )
    metro_min = round((metro_km / 35.0) * 60) + 3  # +3 min boarding/alighting

    total_km  = round(walk_src_km + metro_km + walk_dst_km, 2)
    total_min = walk_src_min + metro_min + walk_dst_min

    # Build segments for frontend display
    segments = [
        {
            "type":        "walk",
            "from":        source,
            "to":          src_station["name"],
            "distance_km": round(walk_src_km, 2),
            "time_min":    walk_src_min,
            "line":        None,
        },
        {
            "type":        "metro",
            "from":        src_station["name"],
            "to":          dst_station["name"],
            "distance_km": round(metro_km, 2),
            "time_min":    metro_min,
            "line":        metro_path[0].get("line", "blue"),
            "stations":    [s["name"] for s in metro_path],
            "num_stops":   len(metro_path) - 1,
        },
        {
            "type":        "walk",
            "from":        dst_station["name"],
            "to":          destination,
            "distance_km": round(walk_dst_km, 2),
            "time_min":    walk_dst_min,
            "line":        None,
        },
    ]

    # Build a composite GeoJSON combining all segments
    all_points = (
        [(src_lat, src_lon), (src_station["lat"], src_station["lon"])]
        + [(s["lat"], s["lon"]) for s in metro_path]
        + [(dst_station["lat"], dst_station["lon"]), (dst_lat, dst_lon)]
    )
    geojson = _straight_geojson(all_points, "Metro Route", total_km, total_min)

    # Coords for spatial corridor matching
    coords = all_points

    # Road names = station names (for display in panel)
    road_names = [s["name"] for s in metro_path]

    return {
        "source":      source,
        "destination": destination,
        "src_coords":  list(src_coords),
        "dst_coords":  list(dst_coords),
        "mode":        "metro",
        "routes": [{
            "id":              0,
            "label":           "Metro Route",
            "road_names":      road_names,
            "distance_km":     total_km,
            "travel_time_min": total_min,
            "geojson":         geojson,
            "node_ids":        [],
            "coords":          coords,
            "mode":            "metro",
            "segments":        segments,
            "metro_stations":  [s["name"] for s in metro_path],
            "walk_src_min":    walk_src_min,
            "walk_dst_min":    walk_dst_min,
            "metro_min":       metro_min,
            "interchange":     any(metro_path[i]["line"] != metro_path[i-1]["line"] for i in range(1, len(metro_path))),
        }],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def get_routes_for_mode(source: str, destination: str, mode: TransportMode) -> dict:
    """
    Compute routes for the given transport mode.

    Returns a dict with shape:
      {source, destination, src_coords, dst_coords, mode, routes: [...]}

    The routes list has the same structure as route_engine.get_multiple_routes()
    plus an extra `mode` key on each route dict.
    """
    if mode == "drive":
        return _road_routes(source, destination, "drive", MODE_SPEED_KMH["drive"])
    elif mode == "walk":
        return _road_routes(source, destination, "walk", MODE_SPEED_KMH["walk"])
    elif mode == "bike":
        return _road_routes(source, destination, "bike", MODE_SPEED_KMH["bike"])
    elif mode == "metro":
        return _metro_route(source, destination)
    else:
        raise ValueError(f"Unknown transport mode: {mode!r}. Use drive/walk/bike/metro.")


def get_metro_geojson_overlay() -> dict:
    """
    Return a GeoJSON FeatureCollection of all metro lines for map overlay.
    Each feature is a LineString for one line, coloured by line.
    """
    features = []

    for line_name, stations in [("blue", _BLUE_LINE), ("green", _GREEN_LINE)]:
        coords = [[s["lon"], s["lat"]] for s in stations]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "line":  line_name,
                "color": LINE_COLORS[line_name],
                "name":  f"Kolkata Metro {'Blue' if line_name == 'blue' else 'Green'} Line",
            }
        })

    # Station points
    for s in METRO_STATIONS:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "id":   s["id"],
                "name": s["name"],
                "line": s["line"],
                "color": LINE_COLORS[s["line"]],
            }
        })

    return {"type": "FeatureCollection", "features": features}
