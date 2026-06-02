"""
web_scraper.py — Official Kolkata traffic advisory scrapers
============================================================
Scrapes real, authoritative traffic disruption information from official
Kolkata government and transport authority websites.

Sources and their status:
  1. Kolkata Police — Google News RSS (official advisories via news)
     Replaces direct site scrape: kolkatapolice.gov.in uses legacy SSL
     that Python 3.11 rejects. Google News RSS reliably surfaces the
     same advisories published by Kolkata Police.

  2. Kolkata Metro (KMRC) — kmrc.in
     Scrapes the KMRC homepage for service notices.
     Falls back to Google News RSS for metro disruption news.

  3. West Bengal Disaster Management — wbdmd.gov.in
     Scrapes flood/cyclone alerts. Falls back to Google News RSS.

  4. Indian Railways — erail.in train running status
     erail.in is a public aggregator with static HTML (unlike NTES which
     is a JS SPA). Fetches delayed trains at Howrah/Sealdah.

  5. KMC Waterlogging — Google News RSS
     KMC site has no structured advisory feed; Google News RSS for
     "Kolkata waterlogging KMC" surfaces the same information reliably.

All scrapers are fault-tolerant — a failed scrape returns [] without
crashing the pipeline.
"""

import requests
from datetime import datetime, timezone, timedelta
from utils.helpers import clean_html
import feedparser
import calendar
from email.utils import parsedate_to_datetime
from ingestion.rss_fetcher import _get_real_url

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False
    print("  [Scraper] beautifulsoup4 not installed — install with: pip install beautifulsoup4 lxml")

# ── Request headers ───────────────────────────────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = 12  # seconds


def _parse_rss_date(entry) -> datetime | None:
    """Parse the published date from an RSS entry into a timezone-aware datetime."""
    # feedparser pre-parses dates into a time.struct_time
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
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


def _age_label_from_dt(pub_dt: datetime | None) -> str:
    """Return a human-readable age string like '2h ago', '3d ago'."""
    if pub_dt is None:
        return "unknown date"
    now   = datetime.now(tz=timezone.utc)
    delta = now - pub_dt
    if delta.total_seconds() < 0:
        return "now"   # future-dated entry — treat as now
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() / 60)}m ago"
    if delta.days < 1:
        return f"{int(delta.total_seconds() / 3600)}h ago"
    return f"{delta.days}d ago"


def _is_recent_dt(pub_dt: datetime | None, max_days: int = 2) -> bool:
    """True if the article is within max_days of today."""
    if pub_dt is None:
        return False   # unknown date = treat as old (strict)
    return (datetime.now(tz=timezone.utc) - pub_dt).total_seconds() / 86400 <= max_days


def _make_article(
    title: str,
    description: str,
    url: str,
    source: str,
    pub_dt: datetime | None = None,
) -> dict:
    """Build a normalised article dict with real publication date."""
    age_label = _age_label_from_dt(pub_dt)
    is_recent = _is_recent_dt(pub_dt) if pub_dt is not None else False
    return {
        "title":        title,
        "description":  description,
        "url":          url,
        "source":       source,
        "age_label":    age_label,
        "is_recent":    is_recent,
        "published_dt": pub_dt,   # datetime | None — used by age filter
    }


def _rss_articles(query: str, source_label: str, max_items: int = 5) -> list[dict]:
    """
    Fetch Google News RSS for a query and return normalised article dicts
    with REAL publication dates parsed from the RSS feed.

    Each article gets:
      age_label    — e.g. "2h ago", "19d ago" (real, not "now")
      is_recent    — True only if published within 2 days
      published_dt — datetime object for precise age filtering
    """
    encoded = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        feed = feedparser.parse(url)
        articles = []
        for entry in feed.entries[:max_items]:
            title    = clean_html(entry.get("title", ""))
            desc     = clean_html(entry.get("summary", ""))
            link     = _get_real_url(entry)   # real publisher URL, not encoded Google News URL
            pub_dt   = _parse_rss_date(entry)
            if title:
                articles.append(_make_article(title, desc, link, source_label, pub_dt))
        return articles
    except Exception as e:
        print(f"  [Scraper] RSS fallback error for '{query}': {e}")
        return []


# ── 1. Kolkata Police Traffic Advisories ─────────────────────────────────────

def fetch_kolkata_police_advisories(max_items: int = 5) -> list[dict]:
    """
    Fetch Kolkata Police traffic advisories via Google News RSS.

    NOTE: The kolkatapolice.gov.in site consistently times out (8+ seconds)
    due to SSL issues and a slow server. We use Google News RSS instead,
    which reliably surfaces the same official advisories.
    """
    print("  [Scraper] Fetching Kolkata Police traffic advisories (via Google News RSS) ...")
    articles = []

    queries = [
        ("Kolkata Police traffic advisory diversion closure", "kolkata_police_advisory"),
        ("Kolkata VIP movement road closure traffic", "kolkata_police_vip"),
        ("Kolkata rally procession traffic block", "kolkata_police_rally"),
    ]

    for query, label in queries:
        items = _rss_articles(query, label, max_items=max_items)
        articles.extend(items)
        if len(articles) >= max_items:
            break

    articles = articles[:max_items]
    print(f"  [Scraper] Got {len(articles)} Kolkata Police advisories")
    return articles


# ── 2. Kolkata Metro (KMRC) Service Disruptions ───────────────────────────────

def fetch_metro_disruptions(max_items: int = 5) -> list[dict]:
    """
    Fetch Kolkata Metro service disruption notices.

    Primary: scrape kmrc.in for notices containing disruption keywords.
    Fallback: Google News RSS for "Kolkata Metro disruption delay".

    The KMRC homepage has general safety/marketing text — we filter
    strictly for disruption-related content only.
    """
    if not _BS4_AVAILABLE:
        return _rss_articles("Kolkata Metro disruption delay suspended", "kmrc_news", max_items)

    articles = []

    # ── Primary: scrape KMRC site ─────────────────────────────────────────────
    try:
        print("  [Scraper] Fetching Kolkata Metro disruption notices ...")
        resp = requests.get("https://www.kmrc.in", headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Strict disruption keywords — avoids picking up marketing/safety text
        disruption_keywords = [
            "disruption", "delay", "suspended", "cancelled", "closed",
            "maintenance", "track work", "service affected", "no service",
            "partial service", "diversion", "non-operational",
        ]

        for tag in soup.find_all(["p", "li", "div", "span", "h3", "h4"])[:150]:
            text = clean_html(tag.get_text())
            if len(text) < 25 or len(text) > 500:
                continue
            # Must contain a disruption keyword AND not be pure navigation/copyright
            nav_indicators = ["copyright", "sitemap", "home |", "career", "rti", "gallery"]
            if any(nav in text.lower() for nav in nav_indicators):
                continue
            if any(kw in text.lower() for kw in disruption_keywords):
                articles.append(_make_article(
                    title=f"[Metro] {text[:100]}",
                    description=text[:500],
                    url="https://www.kmrc.in",
                    source="kmrc_scrape",
                ))
                if len(articles) >= max_items:
                    break

    except requests.exceptions.Timeout:
        print("  [Scraper] KMRC site timed out")
    except Exception as e:
        print(f"  [Scraper] KMRC scrape error: {e}")

    # ── Fallback: Google News RSS if scrape yielded nothing ───────────────────
    if not articles:
        print("  [Scraper] KMRC scrape empty — falling back to Google News RSS")
        articles = _rss_articles(
            "Kolkata Metro Rail disruption delay suspended cancelled station",
            "kmrc_news",
            max_items,
        )
    # If KMRC scrape did return results (from site HTML), they have no date.
    # Replace them with RSS results which have real dates.
    else:
        rss_articles = _rss_articles(
            "Kolkata Metro Rail disruption delay suspended cancelled station",
            "kmrc_news",
            max_items,
        )
        if rss_articles:
            articles = rss_articles   # prefer dated RSS over undated scrape

    print(f"  [Scraper] Got {len(articles)} metro disruption notices")
    return articles


# ── 3. West Bengal Disaster Management — Flood/Cyclone Alerts ────────────────

def fetch_wb_disaster_alerts(max_items: int = 3) -> list[dict]:
    """
    Fetch flood and cyclone alerts for West Bengal.

    Primary: scrape wbdmd.gov.in (often slow/down — 12s timeout).
    Fallback: Google News RSS for "West Bengal flood cyclone alert".
    """
    if not _BS4_AVAILABLE:
        return _rss_articles("West Bengal flood cyclone alert Kolkata", "wb_disaster_news", max_items)

    articles = []

    # ── Primary: scrape WBDMD ─────────────────────────────────────────────────
    try:
        print("  [Scraper] Fetching WB Disaster Management alerts ...")
        resp = requests.get("https://wbdmd.gov.in", headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        alert_keywords = [
            "flood", "cyclone", "alert", "warning", "red alert", "orange alert",
            "heavy rain", "waterlogging", "inundation", "storm", "tidal surge",
        ]

        for tag in soup.find_all(["p", "li", "div", "h3", "h4"])[:100]:
            text = clean_html(tag.get_text())
            if len(text) < 20 or len(text) > 600:
                continue
            if any(kw in text.lower() for kw in alert_keywords):
                articles.append(_make_article(
                    title=f"[WB Disaster] {text[:100]}",
                    description=text[:500],
                    url="https://wbdmd.gov.in",
                    source="wb_disaster_scrape",
                ))
                if len(articles) >= max_items:
                    break

    except requests.exceptions.Timeout:
        print("  [Scraper] WBDMD site timed out — using RSS fallback")
    except Exception as e:
        print(f"  [Scraper] WBDMD scrape error: {e} — using RSS fallback")

    # ── Fallback / override with dated RSS ───────────────────────────────────
    # Scraped HTML has no publication date — always prefer dated RSS articles
    rss = _rss_articles(
        "West Bengal flood cyclone alert warning Kolkata traffic",
        "wb_disaster_news",
        max_items,
    )
    if rss:
        articles = rss   # RSS has real dates; scraped HTML does not
    elif not articles:
        pass   # nothing from either source

    print(f"  [Scraper] Got {len(articles)} WB disaster alerts")
    return articles


# ── 4. Indian Railways — Howrah/Sealdah Train Delays ─────────────────────────

def fetch_train_delays(max_items: int = 5) -> list[dict]:
    """
    Fetch train delay/cancellation news for Howrah and Sealdah.

    Uses Google News RSS for "Howrah Sealdah train delay cancelled" —
    more reliable than scraping NTES (a JS-heavy SPA) or erail.in
    (which requires session cookies).

    Train delays at Howrah/Sealdah cause massive road congestion as
    passengers spill onto roads and buses.
    """
    print("  [Scraper] Fetching Indian Railways train delay info ...")

    articles = _rss_articles(
        "Howrah Sealdah train delay cancelled diverted",
        "indian_railways_news",
        max_items,
    )

    # Also check for broader Eastern Railway disruptions
    if len(articles) < max_items:
        extra = _rss_articles(
            "Eastern Railway disruption Kolkata train",
            "eastern_railway_news",
            max_items - len(articles),
        )
        articles.extend(extra)

    print(f"  [Scraper] Got {len(articles)} railway delay notices")
    return articles[:max_items]


# ── 5. KMC Waterlogging Alerts ────────────────────────────────────────────────

def fetch_kmc_waterlogging(max_items: int = 4) -> list[dict]:
    """
    Fetch KMC waterlogging and road repair alerts via Google News RSS.

    KMC's website (kmcgov.in) has no structured advisory feed.
    Google News RSS for "Kolkata waterlogging KMC" reliably surfaces
    official KMC waterlogging reports and road closure notices.
    """
    print("  [Scraper] Fetching KMC waterlogging alerts ...")

    articles = _rss_articles(
        "Kolkata waterlogging KMC road flooded traffic",
        "kmc_waterlogging",
        max_items,
    )

    print(f"  [Scraper] Got {len(articles)} KMC waterlogging alerts")
    return articles


# ── 6. Consolidated city-wide scrape ─────────────────────────────────────────

def fetch_all_scraped_sources(max_items_each: int = 4) -> list[dict]:
    """
    Run all scrapers and return a combined list of articles.

    Args:
        max_items_each: Max items to fetch from each source.

    Returns:
        Combined list of article-shaped dicts from all scraped sources.
    """
    all_articles = []

    all_articles.extend(fetch_kolkata_police_advisories(max_items=max_items_each))
    all_articles.extend(fetch_metro_disruptions(max_items=max_items_each))
    all_articles.extend(fetch_wb_disaster_alerts(max_items=max_items_each))
    all_articles.extend(fetch_train_delays(max_items=max_items_each))
    all_articles.extend(fetch_kmc_waterlogging(max_items=max_items_each))

    return all_articles
