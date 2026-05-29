import requests
from config import TWITTER_BEARER_TOKEN


SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

# Useful public accounts for Indian city traffic
TRAFFIC_ACCOUNTS = {
    "delhi":   ["@dtptraffic", "@DelhiPolice"],
    "kolkata": ["@KolkataPolice", "@KMCkolkata"],
    "mumbai":  ["@MTPHereToHelp", "@MumbaiPolice"],
}


def _headers() -> dict:
    if not TWITTER_BEARER_TOKEN:
        raise EnvironmentError(
            "TWITTER_BEARER_TOKEN is not set. "
            "Add it to your .env file to enable Twitter ingestion."
        )
    return {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}


def fetch_tweets(query: str, max_results: int = 10) -> list[dict]:
    """
    Search recent tweets matching a query string.

    Args:
        query:       Twitter search query (supports operators like OR, -is:retweet).
        max_results: Number of tweets to return (10–100).

    Returns:
        List of dicts with keys: id, text, created_at, author_id
    """
    try:
        params = {
            "query":       f"{query} -is:retweet lang:en",
            "max_results": max(10, min(max_results, 100)),
            "tweet.fields": "created_at,author_id,text",
        }

        print(f"  [Twitter] Searching: {query}")
        response = requests.get(SEARCH_URL, headers=_headers(), params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        tweets = data.get("data", [])
        print(f"  [Twitter] Got {len(tweets)} tweets")
        return tweets

    except EnvironmentError as e:
        print(f"  [Twitter] Config error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"  [Twitter] Request error: {e}")
    except Exception as e:
        print(f"  [Twitter] Unexpected error: {e}")

    return []


def fetch_traffic_tweets(city: str = "Delhi", road: str = "") -> list[dict]:
    """
    Convenience wrapper — builds a traffic-focused query for a city/road.

    Example query: 'Delhi traffic OR accident OR jam OR closure NH-48'
    """
    base = f"{city} traffic OR accident OR jam OR road closure OR congestion"
    if road:
        base += f" {road}"
    return fetch_tweets(base)


def fetch_account_tweets(account: str, max_results: int = 10) -> list[dict]:
    """
    Fetch recent tweets from a specific account (e.g. @dtptraffic).
    """
    query = f"from:{account.lstrip('@')}"
    return fetch_tweets(query, max_results=max_results)
