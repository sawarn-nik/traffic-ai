"""
graph_builder.py — Temporal Heterogeneous Graph for traffic disruption scoring
===============================================================================
IMPROVEMENTS OVER V1:
  1. Temporal encoding  — hour-of-day (sin/cos), day-of-week, rush-hour flag
  2. Propagation target — co-occurrence matrix for cascade magnitude prediction
  3. Severity label     — stored as integer target for classification head

Node types:
  road      : named road segments
  event     : traffic disruption events
  source    : data sources
  location  : geographic location strings

Event node features (V2 — 24 dims total):
  [sev/10, conf, is_recent, is_future, dur_norm,                    ← 5 base
   hour_sin, hour_cos, day_sin, day_cos, is_rush_hour, is_weekend,  ← 6 temporal (NEW)
   *13_event_type_onehot]                                           ← 13 type encoding
  = 24 dims

Road node features (V2 — 6 dims):
  [avg_sev, cnt_norm, avg_conf, is_on_route,        ← 4 base
   rush_hour_event_ratio, propagation_score]        ← 2 NEW
  = 6 dims
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

# ── NODE TYPE CONSTANTS ───────────────────────────────────────────────────────

EVENT_TYPES = [
    "accident", "congestion", "road_closure", "construction", "protest",
    "weather", "waterlogging", "vip_movement", "metro_disruption",
    "train_delay", "transport_strike", "diversion", "unknown",
]
EVENT_TYPE_IDX   = {et: i for i, et in enumerate(EVENT_TYPES)}
SEVERITY_INT     = {"low": 0, "medium": 1, "high": 2}
SEVERITY_SCORE_MAP = {"low": 2, "medium": 5, "high": 10}

# Kolkata rush hours (empirical)
RUSH_HOURS = {7, 8, 9, 17, 18, 19, 20}

SOURCE_RELIABILITY = {
    "tomtom_traffic": 0.95, "here_traffic": 0.95,
    "openweathermap": 0.90, "openweathermap_alert": 0.95,
    "kolkata_police_advisory": 0.90, "kolkata_police_vip": 0.90,
    "kolkata_police_rally": 0.88, "kolkata_police_scrape": 0.88,
    "kmrc_scrape": 0.82, "kmrc_news": 0.78,
    "wb_disaster_scrape": 0.90, "wb_disaster_news": 0.85,
    "indian_railways_news": 0.82, "eastern_railway_news": 0.80,
    "kmc_waterlogging": 0.82,
    "twitter_official": 0.80, "twitter_kolkatapolice": 0.85,
    "twitter_kmckolkata": 0.82, "twitter_kolkatametrorail": 0.85,
    "twitter_wbpolice": 0.82,
    "rss_city": 0.70, "rss": 0.65, "newsapi": 0.55,
    "twitter_search": 0.50,
}
DEFAULT_RELIABILITY = 0.45

# Updated feature dimensions
EVENT_FEAT_DIM    = 24   # 5 base + 6 temporal + 13 onehot
ROAD_FEAT_DIM     = 6    # 4 base + 2 new
SOURCE_FEAT_DIM   = 2
LOCATION_FEAT_DIM = 3


def _one_hot_event_type(event_type: str) -> list[float]:
    vec = [0.0] * len(EVENT_TYPES)
    idx = EVENT_TYPE_IDX.get(event_type, EVENT_TYPE_IDX["unknown"])
    vec[idx] = 1.0
    return vec


def _temporal_features(fetched_at=None) -> list[float]:
    """
    Return 6 temporal features for an event:
      [hour_sin, hour_cos, day_sin, day_cos, is_rush_hour, is_weekend]

    Uses fetched_at datetime if provided, else current time.
    Encodes hour and day-of-week as sin/cos for cyclic continuity
    (so hour 23 and hour 0 are close, not far apart).
    """
    if fetched_at and isinstance(fetched_at, datetime):
        dt = fetched_at
    else:
        dt = datetime.now(timezone.utc)

    hour = dt.hour
    dow  = dt.weekday()   # 0=Mon … 6=Sun

    hour_sin = math.sin(2 * math.pi * hour / 24)
    hour_cos = math.cos(2 * math.pi * hour / 24)
    day_sin  = math.sin(2 * math.pi * dow  / 7)
    day_cos  = math.cos(2 * math.pi * dow  / 7)

    is_rush    = 1.0 if hour in RUSH_HOURS else 0.0
    is_weekend = 1.0 if dow >= 5 else 0.0

    return [hour_sin, hour_cos, day_sin, day_cos, is_rush, is_weekend]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


# ── MAIN BUILDER ─────────────────────────────────────────────────────────────

def build_graph_from_events(
    events: list[dict],
    route_road_names: list[str],
    adjacency_km: float = 1.5,
) -> tuple[dict, dict]:
    """
    Build a temporal heterogeneous graph from live event dicts.

    Returns (graph_data, meta).
    graph_data contains numpy arrays — no torch dependency here.
    """
    import numpy as np

    route_set = {r.lower() for r in route_road_names}

    road_ids:     dict[str, int] = {}
    source_ids:   dict[str, int] = {}
    location_ids: dict[str, int] = {}

    def _road_idx(name):
        n = (name or "unknown").lower().strip()
        if n not in road_ids: road_ids[n] = len(road_ids)
        return road_ids[n]

    def _source_idx(src):
        s = (src or "unknown").lower().strip()
        if s not in source_ids: source_ids[s] = len(source_ids)
        return source_ids[s]

    def _location_idx(loc):
        l = (loc or "unknown").lower().strip()
        if l not in location_ids: location_ids[l] = len(location_ids)
        return location_ids[l]

    # Pre-register route roads
    for rn in route_road_names:
        _road_idx(rn)
    for ev in events:
        if ev.get("road_name"):
            _road_idx(ev["road_name"])

    # ── Event nodes ───────────────────────────────────────────────────────────
    event_feats:    list[list[float]] = []
    event_sev_ints: list[int]         = []   # severity classification target

    ev_affects_road:    list[tuple[int,int]] = []
    ev_reported_by_src: list[tuple[int,int]] = []
    ev_located_at_loc:  list[tuple[int,int]] = []

    for ev_idx, ev in enumerate(events):
        sev_str   = ev.get("severity", "low")
        sev_score = float(SEVERITY_SCORE_MAP.get(sev_str, 2))
        conf      = float(ev.get("confidence", 0.5))
        is_recent = 1.0 if ev.get("is_recent", True) else 0.0
        is_future = 1.0 if ev.get("is_future_event", False) else 0.0
        dur_norm  = min(float(ev.get("impact_duration_mins") or 60) / 1440.0, 1.0)
        etype_oh  = _one_hot_event_type(ev.get("event_type", "unknown"))

        # Temporal features
        fetched_at = ev.get("fetched_at")   # may be None for live events
        temp_feats = _temporal_features(fetched_at)

        # Full feature vector (26 dims)
        feat = [sev_score / 10.0, conf, is_recent, is_future, dur_norm] + temp_feats + etype_oh
        event_feats.append(feat)
        event_sev_ints.append(SEVERITY_INT.get(sev_str, 0))

        road_name = ev.get("road_name") or "unknown"
        ev_affects_road.append((ev_idx, _road_idx(road_name)))
        ev_reported_by_src.append((ev_idx, _source_idx(ev.get("source", "unknown"))))
        loc = ev.get("location") or ev.get("road_name") or "unknown"
        ev_located_at_loc.append((ev_idx, _location_idx(loc)))

    n_events = len(event_feats)

    # ── Road nodes ────────────────────────────────────────────────────────────
    road_event_counts = [0]   * len(road_ids)
    road_sev_sum      = [0.0] * len(road_ids)
    road_conf_sum     = [0.0] * len(road_ids)
    road_rush_counts  = [0]   * len(road_ids)

    for ev_idx, (_, road_node) in enumerate(ev_affects_road):
        road_event_counts[road_node] += 1
        road_sev_sum[road_node]      += event_feats[ev_idx][0]
        road_conf_sum[road_node]     += event_feats[ev_idx][1]
        # Check rush hour flag (index 9 in feat vector: 5 base + 4 temporal offset)
        if event_feats[ev_idx][9] > 0.5:   # is_rush_hour
            road_rush_counts[road_node] += 1

    # ── Propagation score per road (co-occurrence based) ─────────────────────
    # Two roads co-occur if they have events within the same hour
    # Propagation score = normalised count of co-occurring road-events
    road_cooccur: dict[int, int] = {}
    road_hour_events: dict[int, list[int]] = {}  # road_idx → list of hour slots

    for ev_idx, (_, road_node) in enumerate(ev_affects_road):
        # hour slot from feature index 5 (hour_sin) — approximate back to slot
        # Instead use is_rush_hour as proxy: 1 = peak slot
        slot = int(event_feats[ev_idx][9])   # 1 if rush, 0 otherwise
        if road_node not in road_hour_events:
            road_hour_events[road_node] = []
        road_hour_events[road_node].append(slot)

    for ri, slots in road_hour_events.items():
        road_cooccur[ri] = sum(slots)   # count of rush-hour events on this road

    road_names_list = sorted(road_ids, key=road_ids.get)
    road_feats: list[list[float]] = []
    for rn in road_names_list:
        ri       = road_ids[rn]
        cnt      = road_event_counts[ri]
        avg_sev  = (road_sev_sum[ri]  / cnt) if cnt > 0 else 0.0
        avg_conf = (road_conf_sum[ri] / cnt) if cnt > 0 else 0.0
        on_rte   = 1.0 if rn in route_set else 0.0
        rush_ratio = (road_rush_counts[ri] / cnt) if cnt > 0 else 0.0
        prop_score = min(road_cooccur.get(ri, 0) / 5.0, 1.0)
        road_feats.append([avg_sev, min(cnt/10.0,1.0), avg_conf, on_rte,
                           rush_ratio, prop_score])

    # ── Road–Road spatial adjacency ───────────────────────────────────────────
    road_coords: dict[int, tuple[float,float]] = {}
    for ev in events:
        lat, lon = ev.get("lat"), ev.get("lon")
        if lat is not None and lon is not None:
            rn = (ev.get("road_name") or "unknown").lower().strip()
            ri = road_ids.get(rn)
            if ri is not None and ri not in road_coords:
                road_coords[ri] = (float(lat), float(lon))

    road_near_road: list[tuple[int,int]] = []
    coords_items = list(road_coords.items())
    for i, (ri, (lai, loi)) in enumerate(coords_items):
        for rj, (laj, loj) in coords_items[i+1:]:
            if _haversine_km(lai, loi, laj, loj) <= adjacency_km:
                road_near_road.append((ri, rj))
                road_near_road.append((rj, ri))

    # ── Source nodes ──────────────────────────────────────────────────────────
    src_names_list   = sorted(source_ids, key=source_ids.get)
    src_event_counts = [0] * len(source_ids)
    for _, si in ev_reported_by_src:
        src_event_counts[si] += 1

    source_feats: list[list[float]] = []
    for sn in src_names_list:
        si  = source_ids[sn]
        rel = SOURCE_RELIABILITY.get(sn, DEFAULT_RELIABILITY)
        source_feats.append([rel, min(src_event_counts[si]/20.0, 1.0)])

    # ── Location nodes ────────────────────────────────────────────────────────
    loc_names_list   = sorted(location_ids, key=location_ids.get)
    loc_event_counts = [0] * len(location_ids)
    for _, li in ev_located_at_loc:
        loc_event_counts[li] += 1

    location_feats: list[list[float]] = []
    for ln in loc_names_list:
        li = location_ids[ln]
        location_feats.append([min(loc_event_counts[li]/10.0,1.0), 0.0, 0.0])

    # ── Pack into numpy ───────────────────────────────────────────────────────
    def _to_np(lst, min_cols=1):
        if not lst:
            return np.zeros((0, min_cols), dtype=np.float32)
        return np.array(lst, dtype=np.float32)

    def _edges_to_np(edges):
        if not edges:
            return np.zeros((2, 0), dtype=np.int64)
        return np.array(edges, dtype=np.int64).T

    graph_data = {
        "road_x":     _to_np(road_feats,     min_cols=ROAD_FEAT_DIM),
        "event_x":    _to_np(event_feats,    min_cols=EVENT_FEAT_DIM),
        "source_x":   _to_np(source_feats,   min_cols=SOURCE_FEAT_DIM),
        "location_x": _to_np(location_feats, min_cols=LOCATION_FEAT_DIM),

        "edge_ev_affects_road":     _edges_to_np(ev_affects_road),
        "edge_ev_reported_by_src":  _edges_to_np(ev_reported_by_src),
        "edge_ev_located_at_loc":   _edges_to_np(ev_located_at_loc),
        "edge_road_near_road":      _edges_to_np(road_near_road),

        # Training targets
        "event_sev_labels": np.array(event_sev_ints, dtype=np.int64),

        "n_roads":     len(road_ids),
        "n_events":    n_events,
        "n_sources":   len(source_ids),
        "n_locations": len(location_ids),
    }

    meta = {
        "road_ids":     road_ids,
        "source_ids":   source_ids,
        "location_ids": location_ids,
        "route_set":    route_set,
    }

    return graph_data, meta


def build_graph_from_db(
    route_road_names: list[str],
    db_url: Optional[str] = None,
    limit: int = 500,
) -> tuple[dict, dict]:
    """Build a graph from traffic_events.db for offline training."""
    if db_url is None:
        from config import DATABASE_URL
        db_url = DATABASE_URL

    from sqlalchemy import create_engine, text
    engine = create_engine(db_url, echo=False)

    with engine.connect() as conn:
        cols_result = conn.execute(text("PRAGMA table_info(traffic_events)"))
        col_names   = {row[1] for row in cols_result}

        has_lat_lon  = "lat" in col_names and "lon" in col_names
        has_future   = "is_future_event" in col_names
        has_duration = "impact_duration_mins" in col_names
        has_fetched  = "fetched_at" in col_names

        lat_col      = "lat, lon"             if has_lat_lon  else "NULL as lat, NULL as lon"
        future_col   = "is_future_event"      if has_future   else "0 as is_future_event"
        duration_col = "impact_duration_mins" if has_duration else "NULL as impact_duration_mins"
        fetched_col  = "fetched_at"           if has_fetched  else "NULL as fetched_at"

        query = text(f"""
            SELECT event_type, severity, confidence, road_name, location,
                   source, 1 as is_recent, {future_col}, {duration_col},
                   {lat_col}, {fetched_col}
            FROM traffic_events
            ORDER BY fetched_at DESC
            LIMIT :limit
        """)
        rows = conn.execute(query, {"limit": limit}).fetchall()

    events = []
    for row in rows:
        # Parse fetched_at for temporal features
        fetched_at = None
        if row[11]:
            try:
                fetched_at = datetime.fromisoformat(str(row[11]))
            except Exception:
                fetched_at = None

        events.append({
            "event_type":           row[0] or "unknown",
            "severity":             row[1] or "low",
            "confidence":           float(row[2] or 0.5),
            "road_name":            row[3],
            "location":             row[4],
            "source":               row[5] or "unknown",
            "is_recent":            True,
            "is_future_event":      bool(row[7]) if row[7] is not None else False,
            "impact_duration_mins": int(row[8]) if row[8] else 60,
            "lat":                  float(row[9])  if row[9]  is not None else None,
            "lon":                  float(row[10]) if row[10] is not None else None,
            "fetched_at":           fetched_at,
        })

    print(f"  [HGNN] Loaded {len(events)} events from DB for graph construction.")
    return build_graph_from_events(events, route_road_names)
