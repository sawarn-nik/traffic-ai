"""
rss_fetcher.py — RSS/Atom feed ingestion, Kolkata-focused

Feed priority:
  1. Google News dynamic search (road-specific queries)  ← used by main pipeline
  2. Kolkata-specific static feeds                       ← city-wide context
  3. National feeds                                      ← fallback

Kolkata-specific sources included:
  - Kolkata Police (@KolkataPolice) news mentions via Google News
  - The Telegraph Kolkata
  - Anandabazar Patrika (English feed)
  - Times of India Kolkata edition
  - Hindustan Times Kolkata
"""

import feedparser
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from utils.helpers import clean_html


# ── Real URL extraction ───────────────────────────────────────────────────────

def _get_real_url(entry) -> str:
    """
    Extract the real article URL from a Google News RSS entry.

    Google News RSS entries contain the publisher's article URL in the
    <source> tag's href attribute. The entry.link is an encoded Google
    News redirect URL that cannot be reliably decoded without JavaScript.

    Strategy (in order of reliability):
      1. entry.source.href — publisher URL embedded in <source> tag
      2. entry.links[]     — any non-google.com link in the links list
      3. entry.link        — fallback to the encoded Google News URL

    Args:
        entry: A feedparser entry object

    Returns:
        The best available URL string (real publisher URL when possible).
    """
    # Method 1: source.href contains the publisher's article URL
    source = getattr(entry, "source", None)
    if source:
        # feedparser may expose it as an attribute or dict-like
        href = getattr(source, "href", "") or (source.get("href", "") if hasattr(source, "get") else "")
        if href and "google.com" not in href and href.startswith("http"):
            return href

    # Method 2: check links list for a non-Google URL
    for link in getattr(entry, "links", []):
        href = link.get("href", "")
        if href and "google.com" not in href and href.startswith("http"):
            return href

    # Method 3: fall back to entry.link (encoded Google News URL)
    return entry.get("link", "")


# ── Date helpers ──────────────────────────────────────────────────────────────

def _parse_published(entry) -> datetime | None:
    """
    Parse the published date from an RSS entry into a timezone-aware datetime.
    Tries feedparser's parsed struct first, then raw string parsing.
    Returns None if unparseable.
    """
    # feedparser pre-parses dates into a time.struct_time
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            import calendar
            ts = calendar.timegm(entry.published_parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            pass

    # Fallback: parse the raw RFC-2822 string
    raw = entry.get("published", "")
    if raw:
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            pass

    return None


def _age_label(pub_dt: datetime | None) -> str:
    """Return a human-readable age string like '2h ago', '3d ago', 'unknown'."""
    if pub_dt is None:
        return "unknown date"
    now   = datetime.now(tz=timezone.utc)
    delta = now - pub_dt
    if delta < timedelta(hours=1):
        return f"{int(delta.seconds / 60)}m ago"
    if delta < timedelta(days=1):
        return f"{int(delta.seconds / 3600)}h ago"
    return f"{delta.days}d ago"


def _is_recent(pub_dt: datetime | None, max_days: int = 30) -> bool:
    """True if the article is within max_days of today (or date is unknown)."""
    if pub_dt is None:
        return True   # give benefit of the doubt
    return (datetime.now(tz=timezone.utc) - pub_dt).days <= max_days


# ── Feed registry ─────────────────────────────────────────────────────────────

RSS_FEEDS = {
    # ── Kolkata-specific ──────────────────────────────────────────────────────
    "kolkata_traffic":
        "https://news.google.com/rss/search?q=Kolkata+traffic+disruption&hl=en-IN&gl=IN&ceid=IN:en",

    "kolkata_police_news":
        "https://news.google.com/rss/search?q=Kolkata+Police+traffic+road+closure&hl=en-IN&gl=IN&ceid=IN:en",

    "kolkata_accident":
        "https://news.google.com/rss/search?q=Kolkata+road+accident+jam&hl=en-IN&gl=IN&ceid=IN:en",

    "kolkata_flood_waterlog":
        "https://news.google.com/rss/search?q=Kolkata+waterlogging+flood+traffic&hl=en-IN&gl=IN&ceid=IN:en",

    "kolkata_protest_rally":
        "https://news.google.com/rss/search?q=Kolkata+rally+protest+road+block&hl=en-IN&gl=IN&ceid=IN:en",

    "telegraph_kolkata":
        "https://www.telegraphindia.com/rss/feed/calcutta",

    "toi_kolkata":
        "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms",

    "ht_kolkata":
        "https://news.google.com/rss/search?q=site:hindustantimes.com+Kolkata+traffic&hl=en-IN&gl=IN&ceid=IN:en",

    # ── National fallback ─────────────────────────────────────────────────────
    "ndtv_india":
        "https://feeds.feedburner.com/ndtvnews-india-news",

    "google_news_india_traffic":
        "https://news.google.com/rss/search?q=India+traffic+disruption&hl=en-IN&gl=IN&ceid=IN:en",
}


# ── Core fetcher ──────────────────────────────────────────────────────────────

def fetch_rss(feed_key: str = "kolkata_traffic", max_items: int = 10) -> list[dict]:
    """
    Fetch articles from a named RSS feed or a raw URL.

    Args:
        feed_key:  Key from RSS_FEEDS dict, or a raw URL string.
        max_items: Maximum number of entries to return.

    Returns:
        List of dicts with keys: title, description, link, published, source
    """
    url = RSS_FEEDS.get(feed_key, feed_key)

    try:
        print(f"  [RSS] Fetching: {feed_key}")
        feed = feedparser.parse(url)

        if feed.bozo and feed.bozo_exception:
            # Many feeds trigger bozo for minor XML issues — log but continue
            print(f"  [RSS] Parse warning ({feed_key}): {feed.bozo_exception}")

        articles = []
        for entry in feed.entries[:max_items]:
            pub_dt   = _parse_published(entry)
            real_url = _get_real_url(entry)
            articles.append({
                "title":           clean_html(entry.get("title", "")),
                "description":     clean_html(entry.get("summary", "")),
                "link":            real_url,            # real article URL (or best available)
                "source_url":      real_url,            # alias for display
                "google_news_url": entry.get("link", ""),  # original encoded Google News URL
                "published":       entry.get("published", ""),
                "published_dt":    pub_dt,              # datetime | None
                "age_label":       _age_label(pub_dt),
                "is_recent":       _is_recent(pub_dt),
                "source":          feed_key,
            })

        print(f"  [RSS] Got {len(articles)} articles from {feed_key}")
        return articles

    except Exception as e:
        print(f"  [RSS] Error fetching {feed_key}: {e}")
        return []


# ── Query-based fetcher (used by main pipeline per road) ─────────────────────

def fetch_rss_for_query(query: str, max_items: int = 5) -> list[dict]:
    """
    Fetch Google News RSS results for an arbitrary search query,
    always scoped to Kolkata so road-level searches stay local.

    Examples:
        fetch_rss_for_query("AJC Bose Road traffic")
        fetch_rss_for_query("EM Bypass accident")
        fetch_rss_for_query("Howrah Bridge closure")
    """
    # Append Kolkata context if not already present
    if "kolkata" not in query.lower() and "calcutta" not in query.lower():
        query = f"{query} Kolkata"

    encoded = query.replace(" ", "+")
    url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    )
    return fetch_rss(url, max_items=max_items)


# ── Kolkata city-wide context fetcher ────────────────────────────────────────

def fetch_kolkata_city_feeds(max_items: int = 5) -> list[dict]:
    """
    Pull from all Kolkata-specific static feeds for a broad city-level
    disruption picture. Useful as supplementary context alongside
    road-specific queries.
    """
    kolkata_feeds = [
        "kolkata_traffic",
        "kolkata_police_news",
        "kolkata_accident",
        "kolkata_flood_waterlog",
        "kolkata_protest_rally",
    ]

    all_articles = []
    for feed_key in kolkata_feeds:
        all_articles.extend(fetch_rss(feed_key, max_items=max_items))

    return all_articles
