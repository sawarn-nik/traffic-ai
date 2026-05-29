"""
Layer 1 Pipeline — Traffic Disruption Intelligence (Kolkata)
=============================================================
Data sources:
  1. Google News RSS  — free, no key, road-specific + Kolkata city feeds
  2. NewsAPI          — requires key, supplementary source

LLM stack (LangChain LCEL chain):
  prompt (ChatPromptTemplate — Kolkata-tuned)
    | model (ChatOpenAI → OpenRouter, or ChatGoogleGenerativeAI → Gemini)
    | structured_output (TrafficEventSchema)
    + exponential-backoff retry on 429 rate limits
    + fallback to PydanticOutputParser on empty structured-output responses

Flow:
  1. Ask user for source and destination (Kolkata localities)
  2. Compute driving route on Kolkata OSM graph (cached)
  3. Extract named road segments from route
  4. For each road: fetch road-specific RSS + NewsAPI articles
  5. Also fetch Kolkata city-wide feeds for broader context
  6. Deduplicate; tag each article with age and recency flag
  7. LangChain chain → validated TrafficEventSchema → score → persist
  8. Print summary — recent events separated from historical context
"""

import sys

from routing.route_engine import get_route, extract_road_names
from ingestion.news_fetcher import fetch_news
from ingestion.rss_fetcher import fetch_rss_for_query, fetch_kolkata_city_feeds
from llm.extractor import extract_event
from llm.schema import TrafficEventSchema
from scoring.congestion_score import compute_score, compute_weighted_score
from database.models import TrafficEvent, init_db, get_session
from utils.helpers import build_article_text, now_iso, deduplicate
from config import NEWS_API_KEY

# ── Pipeline constants ────────────────────────────────────────────────────────

MAX_ROADS               = 6   # top N road segments to query
MAX_ARTICLES_PER_SOURCE = 3   # per road per source
MAX_CITY_FEED_ARTICLES  = 4   # from Kolkata city-wide feeds
RECENT_DAYS             = 7   # articles older than this are flagged as historical


# ── User input ────────────────────────────────────────────────────────────────

def _prompt_route() -> tuple[str, str]:
    """
    Interactively ask the user for source and destination.
    Accepts short Kolkata locality names — the route engine appends
    ', Kolkata, India' automatically for geocoding.

    Examples of valid inputs:
        Howrah Station        Park Street
        Salt Lake Sector V    New Town Action Area 1
        Jadavpur              Dum Dum
        Esplanade             Kalighat
    """
    print("\n" + "─" * 60)
    print("  Kolkata Traffic AI — enter your journey details")
    print("  (Use locality names, landmarks, or full addresses)")
    print("─" * 60)

    while True:
        source = input("\n  Source      : ").strip()
        if source:
            break
        print("  ⚠  Source cannot be empty. Please try again.")

    while True:
        destination = input("  Destination : ").strip()
        if destination:
            break
        print("  ⚠  Destination cannot be empty. Please try again.")

    return source, destination


# ── Article fetchers ──────────────────────────────────────────────────────────

def _articles_from_rss(road: str) -> list[dict]:
    """Fetch Google News RSS articles for a specific road in Kolkata."""
    items = fetch_rss_for_query(
        f"{road} traffic",
        max_items=MAX_ARTICLES_PER_SOURCE,
    )
    return [
        {
            "title":        i.get("title", ""),
            "description":  i.get("description", ""),
            "url":          i.get("link", ""),
            "source":       "rss",
            "age_label":    i.get("age_label", "unknown date"),
            "is_recent":    i.get("is_recent", True),
        }
        for i in items
    ]


def _articles_from_newsapi(road: str) -> list[dict]:
    """Fetch NewsAPI articles for a road, scoped to Kolkata."""
    if not NEWS_API_KEY:
        return []
    data = fetch_news(f"{road} Kolkata")
    return [
        {
            "title":       a.get("title", ""),
            "description": a.get("description", ""),
            "url":         a.get("url", ""),
            "source":      "newsapi",
            "age_label":   "unknown date",
            "is_recent":   True,   # NewsAPI returns recent by default
        }
        for a in data.get("articles", [])[:MAX_ARTICLES_PER_SOURCE]
    ]


def _articles_from_city_feeds() -> list[dict]:
    """
    Pull from Kolkata city-wide RSS feeds (police news, waterlogging,
    protests, accidents) to catch disruptions not tied to a specific road.
    """
    items = fetch_kolkata_city_feeds(max_items=MAX_CITY_FEED_ARTICLES)
    return [
        {
            "title":       i.get("title", ""),
            "description": i.get("description", ""),
            "url":         i.get("link", ""),
            "source":      "rss_city",
            "age_label":   i.get("age_label", "unknown date"),
            "is_recent":   i.get("is_recent", True),
            "_road":       "Kolkata (city-wide)",
        }
        for i in items
    ]


# ── Per-article processing ────────────────────────────────────────────────────

def _process_article(article: dict, road: str, session) -> dict | None:
    """
    Run the LangChain extraction chain on one article, score, and persist.
    Returns a result dict on success, None if no event was extracted.
    """
    text = build_article_text(article["title"], article["description"])
    if not text.strip():
        return None

    event: TrafficEventSchema | None = extract_event(text)
    if event is None:
        return None

    road_name = event.road_name or road
    sev_score = compute_score(event.severity.value)
    weighted  = compute_weighted_score(event.severity.value, event.confidence)

    record = TrafficEvent(
        source           = article["source"],
        source_url       = article.get("url"),
        raw_text         = text,
        event_type       = event.event_type.value,
        location         = event.location,
        road_name        = road_name,
        reason           = event.reason,
        time_mentioned   = event.time_mentioned,
        is_future_event  = event.is_future_event,
        severity         = event.severity.value,
        severity_score   = sev_score,
        confidence       = event.confidence,
    )
    session.add(record)
    session.commit()

    return {
        "event_type":      event.event_type.value,
        "location":        event.location,
        "road_name":       road_name,
        "severity":        event.severity.value,
        "confidence":      event.confidence,
        "reason":          event.reason,
        "time_mentioned":  event.time_mentioned,
        "is_future_event": event.is_future_event,
        "severity_score":  sev_score,
        "weighted_score":  weighted,
        "age_label":       article.get("age_label", "unknown date"),
        "is_recent":       article.get("is_recent", True),
    }


# ── Summary helpers ───────────────────────────────────────────────────────────

def _print_event_block(r: dict, indent: str = "    ") -> None:
    age_tag = f"  [{r['age_label']}]" if r["age_label"] != "unknown date" else ""
    stale   = "  ⏳ HISTORICAL" if not r["is_recent"] else ""
    print(f"{indent}• [{r['road_name']}] {r['event_type'].upper()}{age_tag}{stale}")
    print(f"{indent}  Reason  : {r['reason']}")
    if r["location"]:
        print(f"{indent}  Location: {r['location']}")
    if r["time_mentioned"]:
        print(f"{indent}  Time    : {r['time_mentioned']}")


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run():
    # ── Step 0: Get route from user ───────────────────────────────────────────
    source, destination = _prompt_route()

    print("\n" + "=" * 60)
    print("  Kolkata Traffic AI — Layer 1 Disruption Intelligence")
    print(f"  Route  : {source}  →  {destination}")
    print(f"  Time   : {now_iso()}")
    print(f"  Sources: Google News RSS (Kolkata)"
          + (" + NewsAPI" if NEWS_API_KEY else ""))
    print("=" * 60)

    init_db()
    session = get_session()

    # ── Step 1: Compute route ─────────────────────────────────────────────────
    print("\n[1/4] Computing route on Kolkata road network...")
    try:
        graph, route = get_route(source, destination)
    except ValueError as e:
        print(f"\n  ✗ Route error: {e}")
        session.close()
        sys.exit(1)

    roads = extract_road_names(graph, route)
    print(f"      {len(roads)} named road segments found")

    if roads:
        print("      Roads on route:")
        for r in roads[:MAX_ROADS]:
            print(f"        • {r}")

    # ── Step 2: Fetch articles ────────────────────────────────────────────────
    print(f"\n[2/4] Fetching articles (top {MAX_ROADS} roads + city feeds)...")
    all_articles: list[dict] = []

    for road in roads[:MAX_ROADS]:
        print(f"\n  Road: {road}")
        articles = _articles_from_rss(road) + _articles_from_newsapi(road)
        articles = deduplicate(articles, key="url")
        for a in articles:
            a["_road"] = road
        all_articles.extend(articles)
        print(f"    {len(articles)} articles collected")

    print("\n  Fetching Kolkata city-wide feeds...")
    city_articles = _articles_from_city_feeds()
    city_articles = deduplicate(city_articles, key="url")
    all_articles.extend(city_articles)
    print(f"    {len(city_articles)} city-wide articles collected")

    all_articles = deduplicate(all_articles, key="url")
    recent_count = sum(1 for a in all_articles if a.get("is_recent", True))
    print(f"\n      Total unique articles : {len(all_articles)}")
    print(f"      Recent (≤{RECENT_DAYS}d)        : {recent_count}")
    print(f"      Historical (>{RECENT_DAYS}d)      : {len(all_articles) - recent_count}")

    # ── Step 3: LLM extraction ────────────────────────────────────────────────
    print("\n[3/4] Running LangChain extraction chain (Kolkata-tuned)...")
    results = []

    for i, article in enumerate(all_articles, 1):
        road      = article.pop("_road", "unknown")
        src_label = article["source"].upper()
        age_tag   = f"  [{article.get('age_label', '?')}]"
        stale_tag = "  ⏳" if not article.get("is_recent", True) else ""

        print(f"\n  [{i}/{len(all_articles)}] [{src_label}]{age_tag}{stale_tag} {road}")
        print(f"  Title: {article['title'][:80]}")

        result = _process_article(article, road, session)

        if result:
            results.append(result)
            future_flag = "  ⚠ FUTURE" if result["is_future_event"] else ""
            stale_flag  = "  ⏳ OLD"   if not result["is_recent"]    else ""
            print(f"  → {result['event_type']} | {result['severity'].upper()} "
                  f"(σ={result['severity_score']}, "
                  f"κ={result['confidence']:.2f}, "
                  f"weighted={result['weighted_score']})"
                  f"{future_flag}{stale_flag}")
            print(f"  → location : {result['location']}")
            print(f"  → reason   : {result['reason']}")
            if result["time_mentioned"]:
                print(f"  → time     : {result['time_mentioned']}")
        else:
            print("  → No disruption event extracted")

    # ── Step 4: Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[4/4] Route Disruption Summary")
    print("=" * 60)
    print(f"  Route              : {source}  →  {destination}")
    print(f"  Articles processed : {len(all_articles)}")
    print(f"  Events extracted   : {len(results)}")

    if not results:
        print("\n  ✓  No disruption events found for this route.")
    else:
        # Split into recent vs historical
        recent_results = [r for r in results if r["is_recent"]]
        old_results    = [r for r in results if not r["is_recent"]]

        high_r   = [r for r in recent_results if r["severity"] == "high"]
        medium_r = [r for r in recent_results if r["severity"] == "medium"]
        future_r = [r for r in recent_results if r["is_future_event"]]

        print(f"\n  ── Recent events (≤{RECENT_DAYS} days) ──────────────────────")
        print(f"  High severity   : {len(high_r)}")
        print(f"  Medium severity : {len([r for r in recent_results if r['severity'] == 'medium'])}")
        print(f"  Low severity    : {len([r for r in recent_results if r['severity'] == 'low'])}")
        print(f"  Future/planned  : {len(future_r)}")
        print(f"  Historical      : {len(old_results)}  (shown separately below)")

        if high_r:
            print(f"\n  ⚠  HIGH SEVERITY — RECENT DISRUPTIONS ON YOUR ROUTE:")
            for r in high_r:
                _print_event_block(r)

        if medium_r:
            print(f"\n  ⚡  MEDIUM SEVERITY — RECENT:")
            for r in medium_r:
                _print_event_block(r)

        if future_r:
            print(f"\n  📅  UPCOMING / PLANNED DISRUPTIONS:")
            for r in future_r:
                _print_event_block(r)

        if old_results:
            old_high = [r for r in old_results if r["severity"] == "high"]
            print(f"\n  ⏳  HISTORICAL CONTEXT ({len(old_results)} events, "
                  f"{len(old_high)} high-severity) — may not reflect current conditions:")
            for r in old_results[:5]:   # cap display to 5
                _print_event_block(r, indent="    ")
            if len(old_results) > 5:
                print(f"    ... and {len(old_results) - 5} more (see traffic_events.db)")

        # ── Route risk score (recent events only) ─────────────────────────────
        recent_risk = sum(r["weighted_score"] for r in recent_results)
        total_risk  = sum(r["weighted_score"] for r in results)

        print(f"\n  Route risk score (recent) : {recent_risk:.2f}")
        print(f"  Route risk score (all)    : {total_risk:.2f}")

        if recent_risk >= 15:
            print("  ⚠  HIGH RISK — consider an alternative route or departure time.")
        elif recent_risk >= 6:
            print("  ⚡  MODERATE RISK — expect delays on this route.")
        else:
            print("  ✓  LOW RISK — route appears relatively clear right now.")

    print(f"\n  Events saved to: traffic_events.db")
    print("=" * 60)

    session.close()
    return results


if __name__ == "__main__":
    run()
