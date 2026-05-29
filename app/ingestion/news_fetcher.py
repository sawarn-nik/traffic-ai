import requests
from config import NEWS_API_KEY, NEWS_PAGE_SIZE


def fetch_news(query: str) -> dict:
    """
    Fetch traffic-related news articles from NewsAPI for a given query string.
    Returns the full API response dict, or an empty articles list on failure.
    """
    search_query = f'"{query}" AND (traffic OR accident OR congestion OR jam OR closure OR protest)'

    url = (
        "https://newsapi.org/v2/everything?"
        f"q={search_query}"
        "&language=en"
        "&sortBy=publishedAt"
        f"&pageSize={NEWS_PAGE_SIZE}"
        f"&apiKey={NEWS_API_KEY}"
    )

    try:
        print(f"  [NewsAPI] Fetching: {query}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "ok":
            print(f"  [NewsAPI] Non-OK status: {data.get('message', 'unknown error')}")
            return {"articles": []}

        return data

    except requests.exceptions.Timeout:
        print("  [NewsAPI] Timeout")
    except requests.exceptions.RequestException as e:
        print(f"  [NewsAPI] Request error: {e}")
    except Exception as e:
        print(f"  [NewsAPI] Unexpected error: {e}")

    return {"articles": []}
