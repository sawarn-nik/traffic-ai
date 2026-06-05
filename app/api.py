"""
api.py — FastAPI backend for Kolkata Traffic AI map visualisation
=================================================================
Endpoints:
  GET  /                    → serves the Leaflet.js frontend
  GET  /api/locations       → list of valid Kolkata localities
  POST /api/route           → Step 1: compute routes only (~2s, no LLM)
  POST /api/disruptions     → Step 2: fetch data + LLM extraction (~30-60s)

Two-step design: map draws instantly after /api/route, then
/api/disruptions fills in risk scores and event markers.

Run with:
  cd app_rucha
  uvicorn api:app --reload --port 8000
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from routing.route_engine import get_multiple_routes
from ingestion.rss_fetcher import fetch_rss_for_query, fetch_kolkata_city_feeds
from ingestion.news_fetcher import fetch_news
from ingestion.tomtom_fetcher import fetch_tomtom_incidents
from ingestion.weather_fetcher import fetch_weather_conditions
from ingestion.web_scraper import fetch_all_scraped_sources
from llm.extractor import extract_event
from llm.filter import (
    filter_articles, semantic_deduplicate_events,
    filter_by_route_relevance, format_date_ddmmyy, format_today_ddmmyy,
)
from llm.location_resolver import resolve_location
from llm.filter import is_valid_extracted_event, enforce_location_or_drop
from scoring.congestion_score import compute_score, compute_weighted_score
from scoring.confidence import compute_enhanced_confidence, get_source_reliability
from scoring.impact_duration import estimate_impact
from database.models import TrafficEvent, init_db, get_session
from utils.helpers import build_article_text, deduplicate, now_iso
from config import (
    NEWS_API_KEY, TOMTOM_API_KEY, OPENWEATHER_API_KEY,
    ENABLE_TOMTOM, ENABLE_WEATHER, ENABLE_SCRAPER,
    ENABLE_NEWSAPI, ENABLE_RSS,
)

app = FastAPI(title="Kolkata Traffic AI", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_ARTICLES_PER_SOURCE = 3
MAX_CITY_FEED_ARTICLES  = 4

SEVERITY_COLOR = {"high": "#e74c3c", "medium": "#f39c12", "low": "#27ae60"}
RISK_COLOR     = {"HIGH": "#e74c3c", "MODERATE": "#f39c12", "LOW": "#27ae60",
                  "CLEAR": "#27ae60", "CRITICAL": "#8e44ad"}

KOLKATA_LOCATIONS = [
    {"id": 1,  "name": "Howrah Station",        "desc": "Major railway terminus, west bank of Hooghly"},
    {"id": 2,  "name": "Sealdah",               "desc": "Major railway terminus, central Kolkata"},
    {"id": 3,  "name": "Esplanade",             "desc": "City centre, Maidan area"},
    {"id": 4,  "name": "Park Street",           "desc": "Commercial & dining hub, central Kolkata"},
    {"id": 5,  "name": "Salt Lake Sector V",    "desc": "IT hub, eastern Kolkata"},
    {"id": 6,  "name": "New Town Action Area 1","desc": "New township, Rajarhat"},
    {"id": 7,  "name": "Jadavpur",              "desc": "South Kolkata, university area"},
    {"id": 8,  "name": "Dum Dum",               "desc": "North Kolkata, near airport"},
    {"id": 9,  "name": "Kalighat",              "desc": "South Kolkata, temple area"},
    {"id": 10, "name": "Gariahat",              "desc": "South Kolkata, shopping hub"},
    {"id": 11, "name": "Ultadanga",             "desc": "North-central Kolkata, connector hub"},
    {"id": 12, "name": "Tollygunge",            "desc": "South Kolkata, metro terminus"},
    {"id": 13, "name": "Shyambazar",            "desc": "North Kolkata, five-point crossing"},
    {"id": 14, "name": "Behala",                "desc": "South-west Kolkata"},
    {"id": 15, "name": "Barasat",               "desc": "North suburban, NH-12 corridor"},
]


# ── Pydantic request/response models ──────────────────────────────────────────

class RouteRequest(BaseModel):
    source:      str
    destination: str


class RouteSummary(BaseModel):
    id:              int
    label:           str
    distance_km:     float
    travel_time_min: float
    road_names:      list[str]
    geojson:         dict
    coords:          list[list[float]] | None = None
    risk_score:      float | None = None
    risk_level:      str | None = None
    risk_color:      str | None = None
    matched_events:  list[dict] | None = None
    event_count:     int | None = None
    is_best:         bool | None = None


class DisruptionRequest(BaseModel):
    source:      str
    destination: str
    road_names:  list[str]
    routes:      list[RouteSummary] | None = None


# ── City-wide article fetchers ─────────────────────────────────────────────────

def _fetch_citywide(skip_tomtom: bool = False) -> list[dict]:
    """Fetch Weather + Scrapers + city RSS — city-wide sources.
    Pass skip_tomtom=True when TomTom has already been fetched separately."""
    articles: list[dict] = []

    if not skip_tomtom and ENABLE_TOMTOM and TOMTOM_API_KEY:
        for i in fetch_tomtom_incidents(max_items=15):
            articles.append({
                "title":        i["title"],
                "description":  i["description"],
                "url":          i.get("url", ""),
                "tomtom_url":   i.get("tomtom_url", ""),
                "source":       "tomtom_traffic",
                "age_label":    i["age_label"],
                "is_recent":    i["is_recent"],
                "lat":          i.get("lat"),
                "lon":          i.get("lon"),
                "_tomtom_road": i.get("_tomtom_road", ""),
                "_tomtom_category": i.get("_tomtom_category", ""),
                "_tomtom_severity": i.get("_tomtom_severity", "low"),
                "_road":        i.get("_tomtom_road") or "Kolkata (TomTom)",
            })

    if ENABLE_WEATHER and OPENWEATHER_API_KEY:
        for i in fetch_weather_conditions(max_items=3):
            articles.append({
                "title":       i["title"],
                "description": i["description"],
                "url":         i.get("url", ""),
                "source":      i["source"],
                "age_label":   i["age_label"],
                "is_recent":   i["is_recent"],
                "_road":       "Kolkata (weather)",
            })

    if ENABLE_SCRAPER:
        for i in fetch_all_scraped_sources(max_items_each=4):
            articles.append({
                "title":       i["title"],
                "description": i["description"],
                "url":         i.get("url", ""),
                "source":      i["source"],
                "age_label":   i["age_label"],
                "is_recent":   i["is_recent"],
                "_road":       "Kolkata (advisory)",
            })

    if ENABLE_RSS:
        for i in fetch_kolkata_city_feeds(max_items=MAX_CITY_FEED_ARTICLES):
            articles.append({
                "title":       i.get("title", ""),
                "description": i.get("description", ""),
                "url":         i.get("link", ""),
                "source":      "rss_city",
                "age_label":   i.get("age_label", "unknown date"),
                "is_recent":   i.get("is_recent", True),
                "_road":       "Kolkata (city-wide)",
            })

    return deduplicate(articles, key="url")


def _fetch_road_articles(roads: list[str], tomtom_cache: list[dict]) -> list[dict]:
    """
    Fetch per-road articles from TomTom (cached) + RSS + NewsAPI.

    tomtom_cache: pre-fetched full TomTom incident list (passed in to avoid
                  re-calling the API once per road).
    """
    articles: list[dict] = []

    # Build a lowercased set for fast TomTom filtering
    for road in roads:
        road_lower = road.lower()

        # ── TomTom: filter from cache, no new API call ────────────────────────
        if ENABLE_TOMTOM and TOMTOM_API_KEY:
            matched = [
                i for i in tomtom_cache
                if road_lower in i["title"].lower()
                or road_lower in i["description"].lower()
                or road_lower in i.get("_tomtom_road", "").lower()
            ]
            # Fall back to first few city-wide incidents if no road match
            road_incidents = matched[:MAX_ARTICLES_PER_SOURCE] or tomtom_cache[:MAX_ARTICLES_PER_SOURCE]
            for i in road_incidents:
                articles.append({
                    "title":        i["title"],
                    "description":  i["description"],
                    "url":          i.get("url", ""),
                    "tomtom_url":   i.get("tomtom_url", ""),
                    "source":       "tomtom_traffic",
                    "age_label":    i["age_label"],
                    "is_recent":    i["is_recent"],
                    "lat":          i.get("lat"),
                    "lon":          i.get("lon"),
                    "_tomtom_road": i.get("_tomtom_road", ""),
                    "_tomtom_category": i.get("_tomtom_category", ""),
                    "_tomtom_severity": i.get("_tomtom_severity", "low"),
                    "_road":        road,
                })

        if ENABLE_RSS:
            for i in fetch_rss_for_query(f"{road} traffic", max_items=MAX_ARTICLES_PER_SOURCE):
                articles.append({
                    "title":       i.get("title", ""),
                    "description": i.get("description", ""),
                    "url":         i.get("link", ""),
                    "source":      "rss",
                    "age_label":   i.get("age_label", "unknown date"),
                    "is_recent":   i.get("is_recent", True),
                    "_road":       road,
                })

        if ENABLE_NEWSAPI and NEWS_API_KEY:
            data = fetch_news(f"{road} Kolkata")
            for a in data.get("articles", [])[:MAX_ARTICLES_PER_SOURCE]:
                articles.append({
                    "title":       a.get("title", ""),
                    "description": a.get("description", ""),
                    "url":         a.get("url", ""),
                    "source":      "newsapi",
                    "age_label":   a.get("publishedAt", "unknown date"),
                    "is_recent":   True,
                    "_road":       road,
                })

    return deduplicate(articles, key="url")


# ── Event extraction pipeline ──────────────────────────────────────────────────

def _process_articles(articles: list[dict], session) -> list[dict]:
    """
    Run the full extraction pipeline on a list of articles.
    Uses your enhanced pipeline: location resolver, multi-factor confidence,
    impact duration, DB persist — same as main.py.
    """
    results = []

    for raw_article in articles:
        article = dict(raw_article)
        road    = article.get("_road", "unknown")
        text    = build_article_text(article.get("title", ""), article.get("description", ""))
        if not text.strip():
            continue

        source = article.get("source", "")
        event  = extract_event(text, article=article)
        if event is None:
            continue

        if not is_valid_extracted_event(event):
            continue

        resolved_location, loc_source, loc_inferred = resolve_location(
            event, article, road_context=road
        )

        keep, _ = enforce_location_or_drop(
            resolved_location=resolved_location,
            confidence=event.confidence,
            event_type=event.event_type.value,
            source=source,
        )
        if not keep:
            continue

        road_name  = event.road_name or road
        sev_score  = compute_score(event.severity.value)
        enh_conf   = compute_enhanced_confidence(
            llm_confidence    = event.confidence,
            source            = source,
            severity          = event.severity.value,
            location          = resolved_location,
            location_inferred = loc_inferred,
            age_label         = article.get("age_label", "unknown date"),
            is_recent         = article.get("is_recent", True),
        )
        weighted   = compute_weighted_score(event.severity.value, enh_conf)
        api_end    = article.get("_api_end_time")
        duration   = estimate_impact(
            event_type        = event.event_type.value,
            severity          = event.severity.value,
            llm_estimated_end = event.estimated_end_time,
            llm_duration_mins = event.impact_duration_mins,
            api_end_time      = api_end,
            age_label         = article.get("age_label", "unknown date"),
        )
        pub_date   = format_date_ddmmyy(article.get("age_label", "")) or format_today_ddmmyy()

        # Persist
        record = TrafficEvent(
            source               = source,
            source_url           = article.get("url"),
            tomtom_url           = article.get("tomtom_url"),
            raw_text             = text,
            published_date       = pub_date,
            event_type           = event.event_type.value,
            transport_relevant   = getattr(event, "transport_relevant", True),
            location             = resolved_location,
            location_inferred    = loc_inferred,
            location_source      = loc_source,
            road_name            = road_name,
            reason               = event.reason,
            time_mentioned       = event.time_mentioned,
            is_future_event      = event.is_future_event,
            severity             = event.severity.value,
            severity_score       = sev_score,
            confidence           = enh_conf,
            llm_confidence       = event.confidence,
            source_reliability   = get_source_reliability(source),
            start_time_display   = duration["start_time"],
            estimated_end_time   = duration["estimated_end_time"],
            impact_duration_mins = duration["impact_duration_mins"],
            impact_duration_label= duration["impact_duration_label"],
            duration_source      = duration["duration_source"],
        )
        session.add(record)
        session.commit()

        results.append({
            "event_type":           event.event_type.value,
            "location":             resolved_location,
            "location_inferred":    loc_inferred,
            "road_name":            road_name,
            "severity":             event.severity.value,
            "confidence":           enh_conf,
            "reason":               event.reason,
            "time_mentioned":       event.time_mentioned,
            "is_future_event":      event.is_future_event,
            "severity_score":       sev_score,
            "weighted_score":       weighted,
            "age_label":            article.get("age_label", "unknown date"),
            "is_recent":            article.get("is_recent", True),
            "published_date":       pub_date,
            "source":               source,
            "source_url":           article.get("url", ""),
            "tomtom_url":           article.get("tomtom_url", ""),
            "lat":                  article.get("lat"),
            "lon":                  article.get("lon"),
            "impact_duration_label": duration["impact_duration_label"],
            "estimated_end_time":   duration["estimated_end_time"],
            "color":                SEVERITY_COLOR.get(event.severity.value, "#95a5a6"),
        })

    return results


def _score_route(route_data: dict, events: list[dict]) -> dict:
    """Score a route using spatial corridor + road name matching."""
    coords     = route_data.get("coords")
    road_names = route_data.get("road_names", [])

    route_events, _ = filter_by_route_relevance(
        results      = events,
        route_roads  = road_names,
        route_coords = [tuple(c) for c in coords] if coords else None,
        corridor_km  = 2.0,
    )

    recent    = [e for e in route_events if e.get("is_recent", True)
                                         and not e.get("is_future_event", False)]
    risk_score = sum(e["weighted_score"] for e in recent)

    if risk_score >= 25:
        risk_level = "CRITICAL"
    elif risk_score >= 12:
        risk_level = "HIGH"
    elif risk_score >= 5:
        risk_level = "MODERATE"
    elif risk_score > 0:
        risk_level = "LOW"
    else:
        risk_level = "CLEAR"

    return {
        **route_data,
        "risk_score":     round(risk_score, 2),
        "risk_level":     risk_level,
        "risk_color":     RISK_COLOR.get(risk_level, "#27ae60"),
        "matched_events": route_events,
        "event_count":    len(recent),
    }


def _pick_best_route(scored: list[dict]) -> int:
    """Pick best route: lowest composite score (travel_time × (1 + risk/10))."""
    def composite(r):
        return r["travel_time_min"] * (1 + r["risk_score"] / 10)
    return min(range(len(scored)), key=lambda i: composite(scored[i]))


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/locations")
def get_locations():
    return {"locations": KOLKATA_LOCATIONS}


@app.post("/api/route")
def compute_routes_only(req: RouteRequest):
    """
    Step 1 — FAST (~2s). Computes routes via OSMnx, returns GeoJSON.
    No LLM, no news. Map draws immediately.
    All routes get placeholder risk=LOW/score=0 until /api/disruptions runs.
    """
    try:
        result = get_multiple_routes(req.source, req.destination)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Routing error: {e}")

    result.pop("graph")   # OSMnx graph is not JSON-serialisable

    for r in result["routes"]:
        r["risk_score"]     = 0.0
        r["risk_level"]     = "LOW"
        r["risk_color"]     = RISK_COLOR["LOW"]
        r["matched_events"] = []
        r["event_count"]    = 0
        r["is_best"]        = False

    if result["routes"]:
        result["routes"][0]["is_best"] = True

    all_roads = list({road for route in result["routes"] for road in route["road_names"]})

    return {
        **result,
        "all_road_names":     all_roads,
        "disruptions_loaded": False,
        "markers":            [],
        "recent_events":      0,
        "best_route_id":      result["routes"][0]["id"] if result["routes"] else None,
        "generated_at":       now_iso(),
    }


@app.post("/api/disruptions")
def fetch_disruptions(req: DisruptionRequest):
    """
    Step 2 — SLOW (~30-60s). Fetches all sources, runs LLM extraction,
    scores each route spatially, returns updated risk data + event markers.
    """
    events: list[dict] = []
    session = get_session()
    try:
        # ── Fetch TomTom ONCE for the whole city, then reuse ──────────────────
        tomtom_cache: list[dict] = []
        if ENABLE_TOMTOM and TOMTOM_API_KEY:
            raw_tomtom = fetch_tomtom_incidents(max_items=50)
            for i in raw_tomtom:
                tomtom_cache.append({
                    "title":            i["title"],
                    "description":      i["description"],
                    "url":              i.get("url", ""),
                    "tomtom_url":       i.get("tomtom_url", ""),
                    "source":           "tomtom_traffic",
                    "age_label":        i["age_label"],
                    "is_recent":        i["is_recent"],
                    "lat":              i.get("lat"),
                    "lon":              i.get("lon"),
                    "_tomtom_road":     i.get("_tomtom_road", ""),
                    "_tomtom_category": i.get("_tomtom_category", ""),
                    "_tomtom_severity": i.get("_tomtom_severity", "low"),
                    "_road":            i.get("_tomtom_road") or "Kolkata (TomTom)",
                })

        # ── Per-road articles (uses cached TomTom, no extra API calls) ────────
        road_articles = _fetch_road_articles(req.road_names, tomtom_cache)

        # ── City-wide sources (TomTom already fetched, skip re-fetch) ─────────
        city_articles = _fetch_citywide(skip_tomtom=True)
        city_articles.extend(tomtom_cache)

        all_articles = deduplicate(road_articles + city_articles, key="url")

        # Pre-LLM filters
        all_articles, fstats = filter_articles(all_articles, max_age_days=2)
        print(f"  [API] Articles after filter: {fstats['kept']} kept "
              f"(age: {fstats['dropped_age']}, geo: {fstats['dropped_geography']}, "
              f"relevance: {fstats['dropped_relevance']})")

        # LLM extraction
        raw_events = _process_articles(all_articles, session)
        print(f"  [API] Events extracted: {len(raw_events)}")

        # Semantic dedup
        events = semantic_deduplicate_events(raw_events)
        print(f"  [API] After dedup: {len(events)} events")

    except Exception as e:
        import traceback
        print(f"  [API] ERROR in disruption fetch: {e}")
        traceback.print_exc()
        # Return partial results (empty events, scored with 0 risk) rather than 500
    finally:
        session.close()

    # Build route list from request
    route_list = []
    if req.routes:
        for r in req.routes:
            # Pydantic v2 uses model_dump(), v1 uses dict()
            if hasattr(r, "model_dump"):
                route_list.append(r.model_dump())
            elif hasattr(r, "dict"):
                route_list.append(r.dict())
            else:
                route_list.append(dict(r))
    else:
        for idx, rn in enumerate(req.road_names):
            route_list.append({
                "id": idx, "label": f"Route {idx+1}",
                "road_names": [rn], "distance_km": 0.0,
                "travel_time_min": 0.0, "geojson": {},
                "coords": [], "risk_score": 0.0,
                "risk_level": "LOW", "risk_color": RISK_COLOR["LOW"],
                "matched_events": [], "event_count": 0, "is_best": False,
            })

    scored = [_score_route(r, events) for r in route_list]
    best_i = _pick_best_route(scored) if scored else 0
    for i, r in enumerate(scored):
        r["is_best"] = (i == best_i)

    # Build markers — TomTom events use lat/lon, others need geocoding (future work)
    markers = []
    for ev in events:
        if ev.get("is_recent") and ev.get("location"):
            markers.append({
                "location":    ev["location"],
                "event_type":  ev["event_type"],
                "severity":    ev["severity"],
                "reason":      ev["reason"],
                "age_label":   ev.get("age_label", ""),
                "color":       ev.get("color", "#95a5a6"),
                "source":      ev.get("source", ""),
                "source_url":  ev.get("source_url", ""),
                "tomtom_url":  ev.get("tomtom_url", ""),
                "is_future":   ev.get("is_future_event", False),
                "duration":    ev.get("impact_duration_label", ""),
                "lat":         ev.get("lat"),
                "lon":         ev.get("lon"),
            })

    return {
        "routes":        scored,
        "best_route_id": scored[best_i]["id"] if scored else None,
        "events":        events,
        "markers":       markers,
        "total_events":  len(events),
        "recent_events": len([e for e in events if e.get("is_recent")]),
        "generated_at":  now_iso(),
        "source":        req.source,
        "destination":   req.destination,
        "src_coords":    None,
        "dst_coords":    None,
    }


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def frontend():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()