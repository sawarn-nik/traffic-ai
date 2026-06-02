"""
here_fetcher.py — HERE Traffic Incidents API v7
================================================
Fetches real-time traffic incidents (accidents, road closures, construction,
congestion) from HERE's Traffic API for a bounding box around Kolkata.

HERE free tier: 250,000 transactions/month — more than sufficient.
Get a free API key at: https://developer.here.com  (no credit card needed)

Each incident is normalised into the same article-dict shape used by the
rest of the ingestion layer so it flows straight into the LLM extraction
chain without any special handling.

Incident types returned by HERE:
  0 = accident
  1 = congestion
  2 = disabled vehicle
  3 = mass transit
  4 = miscellaneous
  5 = other news
  6 = planned event
  7 = road closure
  8 = road works / construction
  9 = weather
 10 = emergency
"""

import requests
from datetime import datetime, timezone
from config import HERE_API_KEY

# ── Kolkata bounding box ──────────────────────────────────────────────────────
# Covers the full Kolkata Metropolitan Area including Howrah, Salt Lake,
# New Town, Dum Dum, Jadavpur, and surrounding areas.
KOLKATA_BBOX = {
    "south": 22.40,   # southern limit (Budge Budge area)
    "west":  88.20,   # western limit  (Howrah outskirts)
    "north": 22.70,   # northern limit (Dum Dum / Barasat)
    "east":  88.50,   # eastern limit  (New Town / Rajarhat)
}

# HERE incident type → human-readable label
_TYPE_LABELS = {
    0: "accident",
    1: "congestion",
    2: "disabled_vehicle",
    3: "mass_transit",
    4: "miscellaneous",
    5: "other_news",
    6: "planned_event",
    7: "road_closure",
    8: "construction",
    9: "weather",
    10: "emergency",
}

HERE_INCIDENTS_URL = "https://data.traffic.hereapi.com/v7/incidents"


def _severity_from_criticality(criticality: int) -> str:
    """
    Map HERE criticality (0–3) to our severity labels.
      0 = low impact  → low
      1 = minor       → low
      2 = major       → medium
      3 = critical    → high
    """
    if criticality >= 3:
        return "high"
    if criticality >= 2:
        return "medium"
    return "low"


def _age_label(start_time: str | None) -> str:
    """Return a human-readable age string from an ISO-8601 start time."""
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
    """True if the incident started within max_days."""
    if not start_time:
        return True
    try:
        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).days <= max_days
    except Exception:
        return True


def fetch_here_incidents(
    bbox: dict | None = None,
    max_items: int = 20,
) -> list[dict]:
    """
    Fetch real-time traffic incidents from HERE Traffic API v7.

    Args:
        bbox:      Dict with south/west/north/east keys (defaults to Kolkata).
        max_items: Maximum number of incidents to return.

    Returns:
        List of article-shaped dicts compatible with the main pipeline.
        Each dict has: title, description, url, source, age_label, is_recent.
    """
    if not HERE_API_KEY:
        print("  [HERE] API key not set — skipping HERE incidents")
        return []

    if bbox is None:
        bbox = KOLKATA_BBOX

    params = {
        "in":     (
            f"bbox:{bbox['west']},{bbox['south']},"
            f"{bbox['east']},{bbox['north']}"
        ),
        "apiKey": HERE_API_KEY,
    }

    try:
        print("  [HERE] Fetching real-time traffic incidents for Kolkata ...")
        response = requests.get(HERE_INCIDENTS_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        print(f"  [HERE] Got {len(results)} incidents")

        articles = []
        for item in results[:max_items]:
            inc  = item.get("incidentDetails", {})
            loc  = item.get("location", {})

            # ── Extract fields ────────────────────────────────────────────────
            inc_type    = inc.get("type", {}).get("code", 4)
            type_label  = _TYPE_LABELS.get(inc_type, "miscellaneous")
            criticality = inc.get("criticality", {}).get("code", 0)
            severity    = _severity_from_criticality(criticality)
            description = inc.get("description", {}).get("value", "")
            summary     = inc.get("summary", {}).get("value", description)
            road_name   = (
                loc.get("description", {}).get("value", "")
                or loc.get("roadName", "")
            )
            start_time  = inc.get("startTime", "")
            end_time    = inc.get("endTime", "")

            # Build a human-readable title
            title = f"[HERE] {type_label.replace('_', ' ').title()}"
            if road_name:
                title += f" on {road_name}"
            if severity == "high":
                title += " — HIGH SEVERITY"

            # Build description text for LLM
            desc_parts = []
            if summary:
                desc_parts.append(summary)
            if road_name:
                desc_parts.append(f"Location: {road_name}")
            if end_time:
                desc_parts.append(f"Expected until: {end_time}")
            full_desc = " | ".join(desc_parts) if desc_parts else type_label

            articles.append({
                "title":       title,
                "description": full_desc,
                "url":         f"here://incident/{item.get('id', 'unknown')}",
                "source":      "here_traffic",
                "age_label":   _age_label(start_time),
                "is_recent":   _is_recent(start_time),
                # Extra metadata — used for direct structured injection
                "_here_type":     type_label,
                "_here_severity": severity,
                "_here_road":     road_name,
            })

        return articles

    except requests.exceptions.Timeout:
        print("  [HERE] Request timed out")
    except requests.exceptions.HTTPError as e:
        print(f"  [HERE] HTTP error: {e.response.status_code} — {e.response.text[:200]}")
    except requests.exceptions.RequestException as e:
        print(f"  [HERE] Request error: {e}")
    except Exception as e:
        print(f"  [HERE] Unexpected error: {e}")

    return []


def fetch_here_for_road(road: str, max_items: int = 5) -> list[dict]:
    """
    Fetch HERE incidents and filter to those mentioning a specific road name.
    Falls back to the full bbox fetch if no road-specific match is found.

    Args:
        road:      Road name to filter by (e.g. "AJC Bose Road").
        max_items: Max incidents to return.

    Returns:
        Filtered list of article-shaped dicts.
    """
    all_incidents = fetch_here_incidents(max_items=50)
    road_lower = road.lower()

    # Filter incidents that mention this road in title or description
    matched = [
        inc for inc in all_incidents
        if road_lower in inc["title"].lower()
        or road_lower in inc["description"].lower()
        or road_lower in inc.get("_here_road", "").lower()
    ]

    if matched:
        return matched[:max_items]

    # No road-specific match — return top incidents by recency
    return all_incidents[:max_items]
