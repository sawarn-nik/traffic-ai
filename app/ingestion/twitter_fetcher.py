"""
twitter_fetcher.py — Twitter/X API v2 for Kolkata traffic intelligence
=======================================================================
Uses the /2/tweets/search/recent endpoint with targeted queries for
official Kolkata traffic accounts and disruption keywords.

NOTE on Twitter API tiers:
  - Free tier (v2 Basic): search/recent endpoint works but returns
    limited results. User timeline endpoint requires Basic ($100/mo).
  - We use search queries scoped to official accounts (from:username)
    which works on the free tier without needing timeline access.

Key accounts monitored via search:
  @KolkataPolice      — official traffic advisories, VIP movements, closures
  @KMCkolkata         — waterlogging, road repair, civic disruptions
  @KolkataMetroRail   — metro service disruptions, delays, closures
  @WBPolice           — state-level traffic and law-and-order events

Set TWITTER_BEARER_TOKEN in your .env file to enable this source.
"""

import requests
from datetime import datetime, timezone
from config import TWITTER_BEARER_TOKEN

SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

# Official Kolkata traffic-related accounts to monitor via from: operator
KOLKATA_TRAFFIC_ACCOUNTS = [
    "KolkataPolice",
    "KMCkolkata",
    "KolkataMetroRail",
    "WBPolice",
]


def _headers() -> dict | None:
    """Return auth headers, or None if token not configured."""
    if not TWITTER_BEARER_TOKEN:
        return None
    return {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}


def _age_label(created_at: str | None) -> str:
    if not created_at:
        return "unknown date"
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta = now - dt
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta.days < 1:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        return f"{delta.days}d ago"
    except Exception:
        return "unknown date"


def _is_recent(created_at: str | None, max_days: int = 7) -> bool:
    if not created_at:
        return True
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return (datetime.now(tz=timezone.utc) - dt).days <= max_days
    except Exception:
        return True


def _tweet_to_article(tweet: dict, source_label: str) -> dict:
    """Convert a raw tweet dict to a normalised article dict."""
    text       = tweet.get("text", "")
    created_at = tweet.get("created_at", "")
    tweet_id   = tweet.get("id", "unknown")
    return {
        "title":       text[:120],
        "description": text,
        "url":         f"https://twitter.com/i/web/status/{tweet_id}",
        "source":      source_label,
        "age_label":   _age_label(created_at),
        "is_recent":   _is_recent(created_at),
    }


def _search(query: str, max_results: int = 10, source_label: str = "twitter_search") -> list[dict]:
    """
    Internal: run one search query against the v2 recent search endpoint.
    Handles 402 (payment required) and 429 (rate limit) gracefully.
    """
    headers = _headers()
    if not headers:
        return []

    params = {
        "query":        query,
        "max_results":  max(10, min(max_results, 100)),
        "tweet.fields": "created_at,text",
    }

    try:
        response = requests.get(SEARCH_URL, headers=headers, params=params, timeout=10)

        if response.status_code == 402:
            print(f"  [Twitter] Payment required for query — free tier limit reached")
            return []
        if response.status_code == 429:
            print("  [Twitter] Rate limited — skipping")
            return []
        if response.status_code == 401:
            print("  [Twitter] Unauthorized — check TWITTER_BEARER_TOKEN in .env")
            return []

        response.raise_for_status()
        tweets = response.json().get("data", [])
        return [_tweet_to_article(t, source_label) for t in tweets]

    except requests.exceptions.RequestException as e:
        print(f"  [Twitter] Request error: {e}")
    except Exception as e:
        print(f"  [Twitter] Unexpected error: {e}")

    return []


def fetch_kolkata_traffic_tweets(road: str = "", max_results: int = 10) -> list[dict]:
    """
    Fetch Kolkata traffic tweets using targeted search queries.

    Strategy: use `from:account` operator to get official account tweets
    without needing the paid timeline endpoint. Also run a general
    Kolkata traffic keyword search.

    Args:
        road:        Optional road name to include in keyword search.
        max_results: Max tweets per query.

    Returns:
        Combined list of article-shaped dicts.
    """
    headers = _headers()
    if not headers:
        print("  [Twitter] Skipping — TWITTER_BEARER_TOKEN not configured")
        return []

    all_tweets = []

    # ── 1. Official account searches (from: operator — works on free tier) ───
    # Combine all accounts into one query to save API calls
    from_query = " OR ".join(f"from:{acc}" for acc in KOLKATA_TRAFFIC_ACCOUNTS)
    print(f"  [Twitter] Searching official Kolkata traffic accounts ...")
    account_tweets = _search(
        query=f"({from_query}) -is:retweet",
        max_results=max_results,
        source_label="twitter_official",
    )
    print(f"  [Twitter] Got {len(account_tweets)} tweets from official accounts")
    all_tweets.extend(account_tweets)

    # ── 2. Keyword search scoped to Kolkata ───────────────────────────────────
    if road:
        kw_query = f'"{road}" Kolkata (traffic OR accident OR jam OR closure) -is:retweet lang:en'
    else:
        kw_query = (
            "Kolkata (traffic OR accident OR jam OR waterlogging OR "
            "road closure OR rally OR procession OR bandh) -is:retweet lang:en"
        )

    print(f"  [Twitter] Searching Kolkata traffic keywords ...")
    kw_tweets = _search(
        query=kw_query,
        max_results=max_results,
        source_label="twitter_search",
    )
    print(f"  [Twitter] Got {len(kw_tweets)} keyword tweets")
    all_tweets.extend(kw_tweets)

    return all_tweets


# ── Legacy compatibility wrappers ─────────────────────────────────────────────

def fetch_tweets(query: str, max_results: int = 10) -> list[dict]:
    """Legacy wrapper — direct query search."""
    return _search(query, max_results=max_results)


def fetch_traffic_tweets(city: str = "Kolkata", road: str = "") -> list[dict]:
    """Legacy wrapper."""
    return fetch_kolkata_traffic_tweets(road=road, max_results=10)


def fetch_account_tweets(username: str, max_results: int = 10) -> list[dict]:
    """Legacy wrapper — search from a single account."""
    return _search(
        query=f"from:{username.lstrip('@')} -is:retweet",
        max_results=max_results,
        source_label=f"twitter_{username.lower().lstrip('@')}",
    )
