import re
import os
import json
from datetime import datetime


# ── Text utilities ────────────────────────────────────────────────────────────

def clean_html(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_article_text(title: str, description: str) -> str:
    """Combine title and description into a single string for LLM input."""
    parts = [p.strip() for p in (title, description) if p and p.strip()]
    return " ".join(parts)


# ── JSON / file utilities ─────────────────────────────────────────────────────

def safe_json_load(path: str) -> dict | list | None:
    """Load a JSON file, returning None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[helpers] Could not load {path}: {e}")
        return None


def ensure_dir(path: str) -> None:
    """Create directory (and parents) if it doesn't exist."""
    os.makedirs(path, exist_ok=True)


# ── Timestamp ─────────────────────────────────────────────────────────────────

def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.utcnow().isoformat() + "Z"


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(items: list[dict], key: str) -> list[dict]:
    """
    Remove duplicate dicts from a list based on a single key.
    Preserves first occurrence.
    """
    seen = set()
    result = []
    for item in items:
        val = item.get(key)
        if val not in seen:
            seen.add(val)
            result.append(item)
    return result
