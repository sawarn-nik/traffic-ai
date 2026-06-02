"""
tomtom_fetcher.py — TomTom Traffic Incidents API v5
====================================================
Fetches real-time traffic incidents from TomTom for the Kolkata area.

TomTom free tier: 2,500 requests/day — sufficient for this pipeline.
Get a free API key at: https://developer.tomtom.com  (no credit card needed)

Incident iconCategory codes:
  0  = Unknown          6  = Jam / congestion    11 = Flooding
  1  = Accident         7  = Lane closed         14 = Broken down vehicle
  2  = Fog              8  = Road closed
  3  = Dangerous cond.  9  = Road works
  4  = Rain            10  = Wind
  5  = Ice

URL strategy:
  TomTom's API returns incident IDs and geometry (coordinates), not
  web article URLs. We build two real, clickable URLs per incident:
    1. Google Maps deep-link  — opens the exact incident location on
       Google Maps (works in any browser, no account needed)
    2. TomTom Live Traffic    — opens TomTom's web traffic map centred
       on the incident coordinates
  Both URLs are real and navigable.
"""

import requests
from datetime import datetime, timezone
from config import TOMTOM_API_KEY

# ── Kolkata bounding box ──────────────────────────────────────────────────────
KOLKATA_BBOX = "88.20,22.40,88.50,22.70"   # minLon,minLat,maxLon,maxLat

_CATEGORY_LABELS = {
    0:  "unknown",
    1:  "accident",
    2:  "fog",
    3:  "dangerous_conditions",
    4:  "rain",
    5:  "ice",
    6:  "congestion",
    7:  "lane_closed",
    8:  "road_closure",
    9:  "construction",
    10: "wind",
    11: "flooding",
    14: "broken_down_vehicle",
}

# magnitudeOfDelay: 0=unknown/none, 1=minor, 2=moderate, 3=major
_MAGNITUDE_SEVERITY = {0: "low", 1: "low", 2: "medium", 3: "high"}

TOMTOM_INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"

# Two separate requests:
#   1. With fields (properties only, no geometry) — for incident details
#   2. Without fields (geometry only) — for coordinates
# We merge them by index since both return incidents in the same order.
_FIELDS = (
    "{incidents{properties{"
    "id,iconCategory,magnitudeOfDelay,"
    "events{description,code,iconCategory},"
    "startTime,endTime,from,to,delay,roadNumbers"
    "}}}"
)


def _age_label(start_time: str | None) -> str:
    if not start_time:
        return "unknown date"
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta = now - dt
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta.days < 1:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        return f"{delta.days}d ago"
    except Exception:
        return "unknown date"


def _is_recent(start_time: str | None, max_days: int = 7) -> bool:
    if not start_time:
        return True
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).days <= max_days
    except Exception:
        return True


def _build_urls(lon: float, lat: float, cat_label: str) -> tuple[str, str]:
    """
    Build two real, clickable URLs for an incident location.

    Returns:
        (google_maps_url, tomtom_traffic_url)
    """
    zoom = 15   # street-level zoom

    # Google Maps — drops a pin at the exact incident coordinates
    gmaps = (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={lat},{lon}"
    )

    # TomTom Live Traffic map — centred on incident, traffic layer on
    tomtom = (
        f"https://www.tomtom.com/traffic/"
        f"?lat={lat}&lng={lon}&zoom={zoom}"
    )

    return gmaps, tomtom


def _fetch_raw(bbox: str, with_fields: bool) -> list[dict]:
    """Single API call — returns raw incident list."""
    params: dict = {
        "key":                TOMTOM_API_KEY,
        "bbox":               bbox,
        "language":           "en-GB",
        "timeValidityFilter": "present",
    }
    if with_fields:
        params["fields"] = _FIELDS

    resp = requests.get(TOMTOM_INCIDENTS_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("incidents", [])


def fetch_tomtom_incidents(
    bbox: str | None = None,
    max_items: int = 30,
) -> list[dict]:
    """
    Fetch real-time traffic incidents from TomTom Traffic API v5.

    Makes two API calls:
      1. With fields param  → incident details (category, roads, delay, times)
      2. Without fields     → geometry (coordinates for real map URLs)

    Merges both by index to produce complete incident records with
    real, clickable Google Maps and TomTom Traffic URLs.

    Args:
        bbox:      Bounding box "minLon,minLat,maxLon,maxLat"
                   (defaults to Kolkata Metropolitan Area).
        max_items: Maximum number of incidents to return.

    Returns:
        List of article-shaped dicts compatible with the main pipeline.
        Each dict includes:
          url          — Google Maps deep-link to the incident location
          tomtom_url   — TomTom Live Traffic map link
    """
    if not TOMTOM_API_KEY:
        print("  [TomTom] API key not set — skipping TomTom incidents")
        return []

    effective_bbox = bbox or KOLKATA_BBOX

    try:
        print("  [TomTom] Fetching real-time traffic incidents for Kolkata ...")

        # ── Call 1: incident details (properties) ─────────────────────────────
        detail_incidents = _fetch_raw(effective_bbox, with_fields=True)

        # ── Call 2: geometry (coordinates) ────────────────────────────────────
        geo_incidents = _fetch_raw(effective_bbox, with_fields=False)

        # Build a lon/lat lookup by index (both lists are same order/length)
        coords_by_index: dict[int, tuple[float, float]] = {}
        for idx, geo_item in enumerate(geo_incidents):
            geom = geo_item.get("geometry", {})
            coords = geom.get("coordinates", [])
            if coords:
                # Take the first point of the LineString
                first = coords[0]
                if len(first) >= 2:
                    coords_by_index[idx] = (float(first[0]), float(first[1]))  # lon, lat

        total = len(detail_incidents)
        print(f"  [TomTom] Got {total} incidents ({len(coords_by_index)} with coordinates)")

        articles = []
        for idx, item in enumerate(detail_incidents[:max_items]):
            props = item.get("properties", {})

            category   = props.get("iconCategory", 0)
            cat_label  = _CATEGORY_LABELS.get(category, "unknown")
            magnitude  = props.get("magnitudeOfDelay", 0)
            severity   = _MAGNITUDE_SEVERITY.get(magnitude, "low")
            from_road  = props.get("from", "")
            to_road    = props.get("to", "")
            road_nums  = props.get("roadNumbers", [])
            road_name  = road_nums[0] if road_nums else from_road
            start_time = props.get("startTime", "")
            end_time   = props.get("endTime", "")
            delay_secs = props.get("delay") or 0
            inc_id     = props.get("id", f"idx-{idx}")

            # ── Event descriptions ────────────────────────────────────────────
            events      = props.get("events", [])
            event_descs = [e.get("description", "") for e in events if e.get("description")]
            event_text  = "; ".join(event_descs) if event_descs else cat_label.replace("_", " ").title()

            # ── Build real URLs from coordinates ──────────────────────────────
            lon, lat = coords_by_index.get(idx, (88.3639, 22.5726))  # fallback = Kolkata centre
            gmaps_url, tomtom_url = _build_urls(lon, lat, cat_label)

            # ── Title ─────────────────────────────────────────────────────────
            title = f"[TomTom] {cat_label.replace('_', ' ').title()}"
            if from_road:
                title += f" — {from_road}"
                if to_road and to_road != from_road:
                    title += f" to {to_road}"
            if severity == "high":
                title += " — HIGH SEVERITY"

            # ── Description for LLM ───────────────────────────────────────────
            desc_parts = [event_text]
            if from_road:
                loc = f"From {from_road}"
                if to_road and to_road != from_road:
                    loc += f" to {to_road}"
                desc_parts.append(loc)
            if delay_secs and delay_secs > 0:
                desc_parts.append(f"Delay: ~{round(delay_secs / 60)} minutes")
            if end_time:
                desc_parts.append(f"Expected until: {end_time}")

            articles.append({
                "title":       title,
                "description": " | ".join(desc_parts),
                # Primary URL = Google Maps (real, clickable, no account needed)
                "url":         gmaps_url,
                # Secondary URL = TomTom Traffic map
                "tomtom_url":  tomtom_url,
                "source":      "tomtom_traffic",
                "age_label":   _age_label(start_time),
                "is_recent":   _is_recent(start_time),
                # Coordinates for downstream use
                "lat":         lat,
                "lon":         lon,
                # Internal metadata
                "_tomtom_id":       inc_id,
                "_tomtom_category": cat_label,
                "_tomtom_severity": severity,
                "_tomtom_road":     road_name,
            })

        return articles

    except requests.exceptions.Timeout:
        print("  [TomTom] Request timed out")
    except requests.exceptions.HTTPError as e:
        print(f"  [TomTom] HTTP error: {e.response.status_code} — {e.response.text[:200]}")
    except requests.exceptions.RequestException as e:
        print(f"  [TomTom] Request error: {e}")
    except Exception as e:
        print(f"  [TomTom] Unexpected error: {e}")

    return []


def fetch_tomtom_for_road(road: str, max_items: int = 5) -> list[dict]:
    """
    Fetch TomTom incidents and filter to those mentioning a specific road.
    Returns top city-wide incidents if no road-specific match found.
    """
    all_incidents = fetch_tomtom_incidents(max_items=60)
    road_lower = road.lower()

    matched = [
        inc for inc in all_incidents
        if road_lower in inc["title"].lower()
        or road_lower in inc["description"].lower()
        or road_lower in inc.get("_tomtom_road", "").lower()
    ]

    return matched[:max_items] if matched else all_incidents[:max_items]
