"""
filter.py — Article and event filtering pipeline
=================================================
Implements:
  1. Age filter        — discard articles older than MAX_AGE_DAYS (2 days)
                         Uses published_dt (precise) or age_label (fallback)
                         Handles timezone-naive vs aware datetime comparison
  2. Relevance filter  — keep only transportation-related articles
                         Also enforces Kolkata geographic scope
  3. Semantic dedup    — remove duplicate events by (event_type, location, road)
  4. Date formatter    — convert all timestamps to DD/MM/YY
  5. Post-extraction   — discard irrelevant LLM outputs
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────

MAX_AGE_DAYS = 2   # discard articles older than this

# Keywords that indicate a transport-relevant article
_TRANSPORT_KEYWORDS = {
    "traffic", "congestion", "jam", "gridlock", "slow", "blocked",
    "road closure", "road block", "road closed", "diversion", "detour",
    "accident", "crash", "collision", "vehicle", "truck", "bus",
    "road work", "roadwork", "construction", "repair", "pothole",
    "flyover", "bridge", "underpass", "signal", "crossing",
    "waterlog", "waterlogging", "flood", "inundation", "submerged",
    "knee-deep", "ankle-deep", "water-logged",
    "cyclone", "storm", "fog", "visibility", "heavy rain", "downpour",
    "metro", "train", "railway", "tram", "ferry", "auto",
    "sealdah", "howrah", "local train", "suburban",
    "rally", "procession", "protest", "bandh", "strike", "agitation",
    "vip", "convoy", "motorcade", "closure",
    "durga puja", "eid", "brigade", "red road", "em bypass", "ajc bose",
    "vip road", "strand road", "rashbehari", "gariahat", "ultadanga",
    "kona expressway", "nh-12", "nh-16", "nh 12", "nh 16",
    "howrah bridge", "vidyasagar setu", "rabindra setu",
    "advisory", "restriction", "no-entry", "one-way", "divert",
    "roadworks", "stationary traffic", "queuing traffic",  # TomTom terms
}

# Keywords that strongly indicate irrelevant content
_IRRELEVANT_KEYWORDS = {
    "cricket", "ipl", "football", "match", "score", "wicket",
    "bollywood", "movie", "film", "actor", "actress", "celebrity",
    "stock market", "sensex", "nifty", "share price", "ipo",
    "election result", "vote count", "exit poll",
    "copyright", "all rights reserved", "sitemap", "privacy policy",
    "subscribe", "newsletter", "advertisement",
    "airline", "flight cancel", "airport delay",
}

# Kolkata geographic scope keywords — at least one must be present
# for non-API sources (RSS, NewsAPI, scrapers)
_KOLKATA_SCOPE_KEYWORDS = {
    "kolkata", "calcutta", "howrah", "salt lake", "new town", "rajarhat",
    "jadavpur", "dum dum", "kalighat", "gariahat", "ultadanga", "tollygunge",
    "shyambazar", "behala", "barasat", "barrackpore", "sealdah", "esplanade",
    "park street", "em bypass", "vip road", "ajc bose", "strand road",
    "rashbehari", "diamond harbour", "jessore road", "kona expressway",
    "west bengal", "wb", "kolkata metro", "kolkata police", "kmc",
    "howrah bridge", "vidyasagar setu", "rabindra setu",
    "north kolkata", "south kolkata", "central kolkata",
}

# Sources that are always Kolkata-scoped (no geographic check needed)
_ALWAYS_KOLKATA_SOURCES = {
    "tomtom_traffic", "here_traffic", "openweathermap", "openweathermap_alert",
    "kolkata_police_advisory", "kolkata_police_vip", "kolkata_police_rally",
    "kolkata_police_scrape", "kmrc_scrape", "kmrc_news",
    "wb_disaster_scrape", "wb_disaster_news",
    "indian_railways_news", "eastern_railway_news",
    "kmc_waterlogging", "rss_city",
}

# Sources that are REAL-TIME and should skip the age check entirely.
# Only structured APIs that fetch live data belong here.
# Scraper/RSS sources have real publication dates and MUST be age-checked.
_REALTIME_SOURCES = {
    "tomtom_traffic", "here_traffic",
    "openweathermap", "openweathermap_alert",
}

MIN_TEXT_LENGTH = 30


# ── Date utilities ────────────────────────────────────────────────────────────

def parse_age_label_to_hours(age_label: str) -> Optional[float]:
    """Convert '2h ago', '3d ago', '45m ago' to hours. Returns None if unparseable."""
    if not age_label or age_label in ("unknown date", "now"):
        return None
    age_label = age_label.strip().lower()
    m = re.match(r"(\d+)\s*m\s*ago", age_label)
    if m:
        return int(m.group(1)) / 60.0
    m = re.match(r"(\d+)\s*h\s*ago", age_label)
    if m:
        return float(m.group(1))
    m = re.match(r"(\d+)\s*d\s*ago", age_label)
    if m:
        return float(m.group(1)) * 24.0
    return None


def _ensure_aware(dt: datetime) -> datetime:
    """Make a datetime timezone-aware (UTC) if it is naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_date_ddmmyy(dt_str: Optional[str]) -> Optional[str]:
    """
    Convert any timestamp or age_label to DD/MM/YY format.

    Handles:
      - ISO-8601: "2026-05-30T11:45:00Z" → "30/05/26"
      - Date only: "2026-05-30" → "30/05/26"
      - RFC-2822: "Fri, 30 May 2026 11:45:00 +0000" → "30/05/26"
      - Age label: "3h ago" → computed from today
      - None → None
    """
    if not dt_str:
        return None

    # Try ISO formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            s = dt_str.replace("+00:00", "Z")
            if s.endswith("Z"):
                s = s[:-1]
            dt = datetime.strptime(s, fmt.rstrip("Z"))
            return dt.strftime("%d/%m/%y")
        except ValueError:
            continue

    # Try RFC-2822 (RSS published dates)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(dt_str)
        return dt.strftime("%d/%m/%y")
    except Exception:
        pass

    # Try age_label
    hours = parse_age_label_to_hours(dt_str)
    if hours is not None:
        dt = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        return dt.strftime("%d/%m/%y")

    return None


def format_today_ddmmyy() -> str:
    """Return today's date in DD/MM/YY format."""
    return datetime.now(tz=timezone.utc).strftime("%d/%m/%y")


# ── Age filter ────────────────────────────────────────────────────────────────

def is_within_age_limit(
    age_label: str,
    published_dt: Optional[datetime] = None,
    max_days: int = MAX_AGE_DAYS,
) -> bool:
    """
    Return True if the article is within max_days old.

    Uses published_dt (precise) first, then age_label string.
    Handles timezone-naive datetimes by assuming UTC.
    Articles with truly unknown dates are kept (benefit of the doubt).
    """
    # Use precise datetime if available
    if published_dt is not None:
        try:
            aware_dt = _ensure_aware(published_dt)
            age_days = (datetime.now(tz=timezone.utc) - aware_dt).total_seconds() / 86400
            return age_days <= max_days
        except Exception:
            pass  # fall through to age_label

    # Fall back to age_label
    if not age_label or age_label in ("unknown date", "now"):
        # "now" = real-time source, always keep
        # "unknown date" = strict: DROP unless it's a real-time API source
        # (caller handles the API source exception)
        return age_label == "now"

    hours = parse_age_label_to_hours(age_label)
    if hours is None:
        # Unparseable date string — treat as unknown, drop to be safe
        return False

    return hours <= (max_days * 24)


# ── Geographic scope filter ───────────────────────────────────────────────────

def is_kolkata_scoped(title: str, description: str, source: str) -> bool:
    """
    Return True if the article is about Kolkata/West Bengal.

    API sources (TomTom, HERE, Weather) are always Kolkata-scoped.
    For other sources, at least one Kolkata keyword must be present.
    """
    if source in _ALWAYS_KOLKATA_SOURCES:
        return True

    combined = (title + " " + description).lower()
    return any(kw in combined for kw in _KOLKATA_SCOPE_KEYWORDS)


# ── Relevance filter ──────────────────────────────────────────────────────────

def is_transport_relevant(title: str, description: str) -> bool:
    """
    Pre-LLM relevance check based on keyword matching.
    Returns True if the article is likely transportation-related.
    """
    combined = (title + " " + description).lower()

    # Reject if clearly irrelevant (unless transport keyword also present)
    for kw in _IRRELEVANT_KEYWORDS:
        if kw in combined:
            if not any(tk in combined for tk in _TRANSPORT_KEYWORDS):
                return False

    return any(kw in combined for kw in _TRANSPORT_KEYWORDS)


# ── Semantic deduplication ────────────────────────────────────────────────────

def semantic_deduplicate_events(results: list[dict]) -> list[dict]:
    """
    Remove semantically duplicate events from extracted results.

    Two events are considered duplicates if they share:
      - Same event_type AND
      - Same road_name (case-insensitive) AND
      - Similar location (first 30 chars match)

    When duplicates are found, keep the one with:
      1. Higher confidence
      2. More specific location (not None)
      3. Official source (TomTom/HERE over RSS/NewsAPI)

    Args:
        results: List of extracted event result dicts

    Returns:
        Deduplicated list, keeping the best version of each event.
    """
    # Source priority for dedup tie-breaking (lower = higher priority)
    SOURCE_PRIORITY = {
        "tomtom_traffic": 1, "here_traffic": 1,
        "openweathermap": 2, "openweathermap_alert": 2,
        "kolkata_police_advisory": 3, "kolkata_police_vip": 3,
        "kmrc_scrape": 4, "kmrc_news": 4,
        "wb_disaster_scrape": 4, "wb_disaster_news": 4,
        "rss_city": 5, "rss": 6, "newsapi": 7,
    }

    def _dedup_key(r: dict) -> str:
        event_type = r.get("event_type", "unknown")
        road = (r.get("road_name") or "").lower().strip()[:40]
        loc  = (r.get("location") or "").lower().strip()[:30]
        # Include a reason snippet so two different incidents on the same generic
        # road ("Kolkata (city-wide)") don't collapse into one event.
        # Without this, all RSS/NewsAPI articles that share road_name="Kolkata
        # (city-wide)" reduce to a single event regardless of what happened,
        # causing all non-TomTom routes to receive the exact same risk score.
        reason_snippet = (r.get("reason") or "").lower().strip()[:40]
        return f"{event_type}|{road}|{loc}|{reason_snippet}"

    def _priority(r: dict) -> tuple:
        """Lower tuple = higher priority (kept over others)."""
        src_pri = SOURCE_PRIORITY.get(r.get("source", ""), 9)
        has_loc = 0 if r.get("location") else 1
        conf    = -r.get("confidence", 0.0)   # negate: higher conf = lower sort value
        return (src_pri, has_loc, conf)

    seen: dict[str, dict] = {}
    for r in results:
        key = _dedup_key(r)
        if key not in seen:
            seen[key] = r
        else:
            # Keep the higher-priority one
            if _priority(r) < _priority(seen[key]):
                seen[key] = r

    return list(seen.values())


# ── Route relevance filter ────────────────────────────────────────────────────

def _build_route_corridor(
    route_coords: list[tuple[float, float]],
    buffer_km: float = 2.0,
) -> tuple[float, float, float, float] | None:
    """
    Build a bounding box around the route with a buffer.

    Args:
        route_coords: List of (lat, lon) tuples for each node on the route
        buffer_km:    Buffer distance in km to add around the route bbox

    Returns:
        (min_lat, max_lat, min_lon, max_lon) or None if no coords given
    """
    if not route_coords:
        return None

    lats = [c[0] for c in route_coords]
    lons = [c[1] for c in route_coords]

    # 1 degree lat ≈ 111 km, 1 degree lon ≈ 111 * cos(lat) km
    import math
    avg_lat = sum(lats) / len(lats)
    lat_buf = buffer_km / 111.0
    lon_buf = buffer_km / (111.0 * math.cos(math.radians(avg_lat)))

    return (
        min(lats) - lat_buf,
        max(lats) + lat_buf,
        min(lons) - lon_buf,
        max(lons) + lon_buf,
    )


def _point_in_corridor(
    lat: float,
    lon: float,
    corridor: tuple[float, float, float, float],
) -> bool:
    """Return True if (lat, lon) falls within the corridor bounding box."""
    min_lat, max_lat, min_lon, max_lon = corridor
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def filter_by_route_relevance(
    results: list[dict],
    route_roads: list[str],
    source: str = "",
    destination: str = "",
    route_coords: list[tuple[float, float]] | None = None,
    corridor_km: float = 1.0,
) -> tuple[list[dict], list[dict]]:
    """
    Split events into route-relevant and city-wide using spatial filtering.

    Strategy (in priority order):
      1. TomTom/HERE events WITH coordinates → check if lat/lon falls within
         a corridor bounding box around the route (1 km buffer for Kolkata's
         dense road network — 2 km caused all central routes to match identically).
         If no route_coords provided, falls back to road name matching.
      2. TomTom/HERE events WITHOUT coordinates → road name matching.
      3. All other sources → road name / location text matching.

    Token matching rules (tightened to avoid false positives in dense city):
      - Full road names always match (e.g. "park street" matches "park street")
      - Individual word tokens require ≥ 6 chars (was 4) to avoid common short
        words like "road", "lane", "park", "bose" matching across different roads
      - Generic location words are excluded from the token set

    Args:
        results:      All extracted events
        route_roads:  Named road segments on the computed route
        source:       Journey source locality name
        destination:  Journey destination locality name
        route_coords: List of (lat, lon) for each OSMnx node on the route
        corridor_km:  Buffer around route bbox in km (default 1 km)

    Returns:
        (route_events, citywide_events) tuple
    """
    if not results:
        return [], []

    # Generic words that appear in many road names and cause false positives.
    # These must NOT be used as standalone match tokens.
    _GENERIC_ROAD_WORDS = {
        "road", "lane", "street", "avenue", "sarani", "marg", "path",
        "nagar", "para", "bazar", "bagan", "ghat", "more", "gate",
        "north", "south", "east", "west", "new", "old", "main",
        "park", "lake", "town", "city", "ring", "link", "cross",
        "bose", "roy", "das", "sen", "lal", "pur", "pore",
    }

    # Build spatial corridor if route coordinates are available
    corridor = _build_route_corridor(route_coords, buffer_km=corridor_km) if route_coords else None

    # Build two-tier token set:
    #   full_names  — complete road/place names (highest precision)
    #   word_tokens — individual words ≥ 6 chars, excluding generic words
    full_names:  set[str] = set()
    word_tokens: set[str] = set()

    for road in (route_roads or []):
        r_lower = road.lower().strip()
        full_names.add(r_lower)
        for word in r_lower.split():
            if len(word) >= 6 and word not in _GENERIC_ROAD_WORDS:
                word_tokens.add(word)

    for place in (source, destination):
        if place:
            p_lower = place.lower().strip()
            full_names.add(p_lower)
            for word in p_lower.split():
                if len(word) >= 6 and word not in _GENERIC_ROAD_WORDS:
                    word_tokens.add(word)

    def _matches_route(event_road: str, event_loc: str) -> bool:
        """
        Return True if the event road/location matches this route.

        Two-pass check:
          1. Full road name substring match (high precision)
          2. Significant word token match (≥ 6 chars, non-generic)
        """
        combined = (event_road + " " + event_loc).lower()

        # Pass 1: full road name
        for name in full_names:
            if len(name) >= 6 and name in combined:
                return True

        # Pass 2: significant word tokens
        combined_words = set(combined.split())
        for token in word_tokens:
            if token in combined_words:   # whole-word match only
                return True

        return False

    route_events: list[dict] = []
    citywide_events: list[dict] = []

    for r in results:
        source_label = r.get("source", "")
        is_api = source_label in ("tomtom_traffic", "here_traffic")

        # ── Spatial check for API sources with coordinates ────────────────────
        if is_api:
            lat = r.get("lat")
            lon = r.get("lon")

            if lat is not None and lon is not None and corridor is not None:
                # We have both coordinates and a corridor — use spatial filter
                if _point_in_corridor(float(lat), float(lon), corridor):
                    route_events.append(r)
                else:
                    citywide_events.append(r)
                continue
            # else: fall through to road name matching below

        # ── Road name / location text matching ────────────────────────────────
        event_road = (r.get("road_name") or "").lower()
        event_loc  = (r.get("location") or "").lower()

        if _matches_route(event_road, event_loc):
            route_events.append(r)
        else:
            citywide_events.append(r)

    return route_events, citywide_events


# ── Main article filter ───────────────────────────────────────────────────────

def filter_articles(
    articles: list[dict],
    max_age_days: int = MAX_AGE_DAYS,
) -> tuple[list[dict], dict]:
    """
    Apply all pre-LLM filters to a list of articles:
      1. Empty text check
      2. Age filter (≤ max_age_days)
      3. Geographic scope (Kolkata only)
      4. Transport relevance (keyword-based)

    Args:
        articles:     List of article dicts from ingestion layer
        max_age_days: Maximum article age to keep (default: 2 days)

    Returns:
        (kept, stats) where stats has counts for each filter stage.
    """
    stats = {
        "total":             len(articles),
        "kept":              0,
        "dropped_age":       0,
        "dropped_relevance": 0,
        "dropped_geography": 0,
        "dropped_empty":     0,
    }

    kept = []
    for article in articles:
        title       = article.get("title", "")
        description = article.get("description", "")
        age_label   = article.get("age_label", "unknown date")
        pub_dt      = article.get("published_dt")
        source      = article.get("source", "")

        # ── 1. Empty text ─────────────────────────────────────────────────────
        if len((title + " " + description).strip()) < MIN_TEXT_LENGTH:
            stats["dropped_empty"] += 1
            continue

        # ── 2. Age filter ─────────────────────────────────────────────────────
        # Only real-time API sources skip the age check.
        # Scraper/RSS sources have real publication dates — always age-check them.
        if source not in _REALTIME_SOURCES:
            if not is_within_age_limit(age_label, pub_dt, max_days=max_age_days):
                stats["dropped_age"] += 1
                continue

        # ── 3. Geographic scope ───────────────────────────────────────────────
        if not is_kolkata_scoped(title, description, source):
            stats["dropped_geography"] += 1
            continue

        # ── 4. Transport relevance ────────────────────────────────────────────
        if source not in _ALWAYS_KOLKATA_SOURCES:
            if not is_transport_relevant(title, description):
                stats["dropped_relevance"] += 1
                continue

        kept.append(article)

    stats["kept"] = len(kept)
    return kept, stats


# ── Post-extraction event filter ──────────────────────────────────────────────

# Confidence threshold above which we keep an event even without a location
HIGH_CONFIDENCE_THRESHOLD = 0.60

def is_valid_extracted_event(event) -> bool:
    """
    Post-LLM filter: discard events that are not transport-relevant,
    have zero confidence, or are clearly not about Kolkata.
    NOTE: Location enforcement is handled separately in enforce_location_or_drop()
    so that the location resolver gets a chance to run first.
    """
    if event is None:
        return False

    if hasattr(event, "transport_relevant") and not event.transport_relevant:
        return False

    if event.event_type.value == "unknown" and event.confidence < 0.1:
        return False

    if event.confidence < 0.15:
        return False

    return True


def enforce_location_or_drop(
    resolved_location: str | None,
    confidence: float,
    event_type: str,
    source: str,
) -> tuple[bool, str]:
    """
    Enforce the location requirement on an extracted event.

    Rules:
      1. If location is present → always keep.
      2. If location is missing AND confidence >= HIGH_CONFIDENCE_THRESHOLD
         → keep, but mark as location-unknown (high-confidence event).
      3. If location is missing AND confidence < HIGH_CONFIDENCE_THRESHOLD
         → drop (unreliable event with no location).
      4. Exception: TomTom/HERE events always kept (structured API, location
         will be resolved from coordinates even if text inference failed).

    Args:
        resolved_location: Location string after all resolution attempts, or None
        confidence:        Enhanced confidence score
        event_type:        Event type string
        source:            Article source identifier

    Returns:
        (keep: bool, reason: str)
    """
    # Structured API sources always have coordinates — keep regardless
    if source in ("tomtom_traffic", "here_traffic"):
        return True, "api_source"

    # Location found — keep
    if resolved_location:
        return True, "location_found"

    # No location but high confidence — keep with warning
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return True, "high_confidence_no_location"

    # No location and low confidence — drop
    return False, f"dropped_no_location_low_confidence_{confidence:.2f}"
