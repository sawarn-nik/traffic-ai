"""
location_resolver.py — Location inference for traffic events
=============================================================
When the LLM cannot extract a location directly from text, this module
tries to infer it using multiple fallback strategies:

  1. Coordinates (TomTom/HERE geometry) → reverse geocode to road/area name
  2. Road name in description → use as location
  3. Known Kolkata landmarks in text → map to area
  4. Route context → use the road segment being queried as fallback

All inferred locations are marked with location_inferred=True and the
appropriate location_source value.
"""

import re
import requests
from typing import Optional
from config import ENABLE_NOMINATIM

# ── Reverse geocode cache (avoid repeated Nominatim calls) ───────────────────
_geocode_cache: dict[tuple[float, float], Optional[str]] = {}

# ── Kolkata landmark → area mapping ──────────────────────────────────────────
# Maps well-known landmarks to their road/area context for location inference

LANDMARK_TO_AREA: dict[str, str] = {
    # Stations
    "howrah station":        "Howrah Station approach roads",
    "howrah bridge":         "Howrah Bridge / Rabindra Setu",
    "sealdah":               "Sealdah Station area, APC Road",
    "dum dum":               "Dum Dum, Jessore Road",
    "barasat":               "Barasat, NH-12",
    "new town":              "New Town, Rajarhat",
    "salt lake":             "Salt Lake, EM Bypass",
    "sector v":              "Salt Lake Sector V, EM Bypass",
    # Bridges
    "vidyasagar setu":       "Vidyasagar Setu (2nd Hooghly Bridge)",
    "2nd hooghly bridge":    "Vidyasagar Setu",
    "rabindra setu":         "Rabindra Setu / Howrah Bridge",
    # Major intersections / areas
    "esplanade":             "Esplanade, Red Road area",
    "park street":           "Park Street, AJC Bose Road",
    "park circus":           "Park Circus, AJC Bose Road",
    "ruby":                  "EM Bypass, Ruby crossing",
    "ultadanga":             "Ultadanga Connector, VIP Road",
    "shyambazar":            "Shyambazar five-point crossing",
    "kalighat":              "Kalighat, Rashbehari Avenue",
    "gariahat":              "Gariahat, Rashbehari Avenue",
    "jadavpur":              "Jadavpur, Rashbehari Avenue",
    "tollygunge":            "Tollygunge, Diamond Harbour Road",
    "behala":                "Behala, Diamond Harbour Road",
    "brigade":               "Brigade Parade Ground, Red Road",
    "red road":              "Red Road, Maidan area",
    "maidan":                "Maidan, Red Road / Strand Road",
    "strand road":           "Strand Road, riverfront",
    "kona":                  "Kona Expressway, NH-16",
    "dankuni":               "Dankuni, NH-19",
    "barrackpore":           "Barrackpore, Jessore Road",
    # Metro stations
    "dum dum metro":         "Dum Dum Metro, Jessore Road",
    "noapara":               "Noapara, Jessore Road",
    "kavi subhas":           "Kavi Subhas Metro, Garia",
    "joka":                  "Joka, Diamond Harbour Road",
    "howrah maidan":         "Howrah Maidan Metro, Howrah",
    # Highways
    "nh-12":                 "NH-12, Jessore Road corridor",
    "nh-16":                 "NH-16, Kona Expressway corridor",
    "nh 12":                 "NH-12, Jessore Road corridor",
    "nh 16":                 "NH-16, Kona Expressway corridor",
    "em bypass":             "EM Bypass",
    "vip road":              "VIP Road",
    "ajc bose":              "AJC Bose Road",
    "rashbehari":            "Rashbehari Avenue",
    "diamond harbour":       "Diamond Harbour Road",
    "jessore road":          "Jessore Road, NH-12",
}

# Kolkata Metro line → corridor description
METRO_LINE_TO_CORRIDOR: dict[str, str] = {
    "blue line":    "Blue Line — Dum Dum to Kavi Subhas (North-South)",
    "green line":   "Green Line — Salt Lake Sector V to Howrah Maidan (East-West)",
    "orange line":  "Orange Line — Noapara to Airport",
    "purple line":  "Purple Line — Joka to Esplanade",
    "north-south":  "Blue Line — Dum Dum to Kavi Subhas",
    "east-west":    "Green Line — Salt Lake Sector V to Howrah Maidan",
}


def infer_location_from_text(text: str) -> tuple[Optional[str], str]:
    """
    Try to infer a location from article text using landmark/road matching.

    Args:
        text: Combined title + description text

    Returns:
        (location, source) where source is one of:
          'road_name'  — found a road name in text
          'landmark'   — matched a known landmark
          'unknown'    — could not infer
    """
    text_lower = text.lower()

    # ── 1. Check for explicit road names ─────────────────────────────────────
    road_patterns = [
        r'\b(AJC Bose Road|EM Bypass|VIP Road|Jessore Road|Diamond Harbour Road)\b',
        r'\b(Strand Road|Rashbehari Avenue|Gariahat Road|Ultadanga Connector)\b',
        r'\b(Kona Expressway|NH-12|NH-16|NH 12|NH 16)\b',
        r'\b(Howrah Bridge|Vidyasagar Setu|Rabindra Setu|2nd Hooghly Bridge)\b',
        r'\b(Red Road|Park Street|APC Road|Circular Road|Bypass Road)\b',
        r'\b([A-Z][a-z]+ Road|[A-Z][a-z]+ Street|[A-Z][a-z]+ Avenue|[A-Z][a-z]+ Lane)\b',
    ]
    for pattern in road_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0), "road_name"

    # ── 2. Check for known landmarks ──────────────────────────────────────────
    for landmark, area in LANDMARK_TO_AREA.items():
        if landmark in text_lower:
            return area, "landmark"

    # ── 3. Check for metro line references ───────────────────────────────────
    for line_kw, corridor in METRO_LINE_TO_CORRIDOR.items():
        if line_kw in text_lower:
            return corridor, "landmark"

    return None, "unknown"


def reverse_geocode_coordinates(lat: float, lon: float) -> Optional[str]:
    """
    Reverse geocode coordinates to a human-readable road/area name
    using the Nominatim (OpenStreetMap) API.

    Results are cached in-process to avoid repeated API calls for the
    same coordinates (TomTom often returns many incidents on the same road).
    """
    # Round to 4 decimal places (~11m precision) for cache key
    cache_key = (round(lat, 4), round(lon, 4))
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    result = None
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat":    lat,
            "lon":    lon,
            "format": "json",
            "zoom":   17,
            "addressdetails": 1,
        }
        headers = {"User-Agent": "KolkataTrafficAI/1.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        addr = data.get("address", {})
        parts = []

        road = addr.get("road") or addr.get("pedestrian") or addr.get("path")
        if road:
            parts.append(road)

        neighbourhood = (
            addr.get("neighbourhood")
            or addr.get("suburb")
            or addr.get("quarter")
        )
        if neighbourhood:
            parts.append(neighbourhood)

        district = addr.get("city_district") or addr.get("county")
        if district and district not in parts:
            parts.append(district)

        if parts:
            result = ", ".join(parts[:2])
        else:
            display = data.get("display_name", "")
            if display:
                result = display.split(",")[0].strip()

    except Exception:
        pass

    _geocode_cache[cache_key] = result
    return result


def resolve_location(
    event,
    article: dict,
    road_context: str = "",
) -> tuple[Optional[str], str, bool]:
    """
    Resolve the best available location for an extracted event.

    Priority order:
      1. LLM-extracted location (direct, not inferred)
      2. TomTom from_road field (structured, reliable)
      3. Reverse geocode from TomTom/HERE coordinates (Nominatim)
      4. LLM-inferred location
      5. Infer from article text (road names, landmarks)
      6. Use road_context (the road segment being queried)
      7. None
    """
    # ── 1. LLM extracted a location directly ─────────────────────────────────
    if event.location and not getattr(event, "location_inferred", False):
        return event.location, "direct", False

    # ── 2. TomTom structured road name (from_road field in article) ──────────
    tomtom_road = article.get("_tomtom_road") or article.get("_here_road")
    if tomtom_road and tomtom_road.strip():
        return tomtom_road.strip(), "road_name", False

    # ── 3. Reverse geocode from coordinates (TomTom/HERE geometry) ───────────
    lat = article.get("lat")
    lon = article.get("lon")
    if lat and lon and ENABLE_NOMINATIM:
        geo_location = reverse_geocode_coordinates(float(lat), float(lon))
        if geo_location:
            return geo_location, "coordinates", True

    # ── 4. LLM inferred a location ────────────────────────────────────────────
    if event.location and getattr(event, "location_inferred", False):
        loc_src = getattr(event, "location_source", None)
        src_val = loc_src.value if hasattr(loc_src, "value") else str(loc_src or "llm_inferred")
        return event.location, src_val, True

    # ── 5. Infer from article text ────────────────────────────────────────────
    text = (article.get("title", "") + " " + article.get("description", "")).strip()
    inferred_loc, inferred_src = infer_location_from_text(text)
    if inferred_loc:
        return inferred_loc, inferred_src, True

    # ── 6. Use road context from route engine ─────────────────────────────────
    _generic_contexts = {
        "unknown", "Kolkata (city-wide)", "Kolkata (HERE incident)",
        "Kolkata (TomTom incident)", "Kolkata (weather)",
        "Kolkata (Twitter)", "Kolkata (official advisory)",
    }
    if road_context and road_context not in _generic_contexts:
        return road_context, "road_name", True

    # ── 7. No location available ──────────────────────────────────────────────
    return None, "unknown", False
