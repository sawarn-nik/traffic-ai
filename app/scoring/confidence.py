"""
confidence.py — Multi-factor confidence scoring for traffic events
==================================================================
Enhances the raw LLM confidence score (κ_llm) with additional signals:

  Final κ = clip(
      w_llm    × κ_llm
    + w_source × source_reliability
    + w_sev    × severity_bonus
    + w_loc    × location_bonus
    + w_time   × recency_bonus
    + multi_source_bonus
  )

Source reliability scores (empirically assigned):
  tomtom_traffic / here_traffic  → 0.95  (real-time structured API)
  openweathermap_alert           → 0.95  (government-issued alert)
  openweathermap                 → 0.90  (official weather service)
  kolkata_police_*               → 0.90  (official police advisory)
  wb_disaster_*                  → 0.90  (government disaster management)
  kmrc_*                         → 0.82  (official metro authority)
  indian_railways_* / eastern_*  → 0.82  (official railways)
  kmc_*                          → 0.82  (official municipal corporation)
  twitter_official               → 0.80  (official account tweets)
  rss_city                       → 0.70  (established news outlets)
  rss                            → 0.65  (Google News RSS)
  newsapi                        → 0.55  (mixed quality news sources)
  twitter_search                 → 0.50  (general public tweets)
  unknown                        → 0.40  (unknown source)
"""

from typing import Optional

# ── Source reliability scores ─────────────────────────────────────────────────

SOURCE_RELIABILITY: dict[str, float] = {
    "tomtom_traffic":           0.95,
    "here_traffic":             0.95,
    "openweathermap":           0.90,
    "openweathermap_alert":     0.95,
    "kolkata_police_advisory":  0.90,
    "kolkata_police_vip":       0.90,
    "kolkata_police_rally":     0.88,
    "kolkata_police_scrape":    0.88,
    "kmrc_scrape":              0.82,
    "kmrc_news":                0.78,
    "wb_disaster_scrape":       0.90,
    "wb_disaster_news":         0.85,
    "indian_railways_news":     0.82,
    "eastern_railway_news":     0.80,
    "kmc_waterlogging":         0.82,
    "twitter_official":         0.80,
    "twitter_kolkatapolice":    0.85,
    "twitter_kmckolkata":       0.82,
    "twitter_kolkatametrorail": 0.85,
    "twitter_wbpolice":         0.82,
    "rss_city":                 0.70,
    "rss":                      0.65,
    "newsapi":                  0.55,
    "twitter_search":           0.50,
}

DEFAULT_SOURCE_RELIABILITY = 0.45

SEVERITY_BONUS: dict[str, float] = {
    "high":   0.08,
    "medium": 0.04,
    "low":    0.00,
}

# Weights — must sum to ≤ 1.0 (multi_bonus is additive on top)
W_LLM    = 0.45
W_SOURCE = 0.30
W_SEV    = 0.08
W_LOC    = 0.10
W_TIME   = 0.07


def get_source_reliability(source: str) -> float:
    """Return the reliability score for a given source."""
    return SOURCE_RELIABILITY.get(source, DEFAULT_SOURCE_RELIABILITY)


def compute_enhanced_confidence(
    llm_confidence: float,
    source: str,
    severity: str,
    location: Optional[str],
    location_inferred: bool,
    age_label: str,
    is_recent: bool,
    confirmed_by_multiple_sources: bool = False,
) -> float:
    """
    Compute an enhanced confidence score combining multiple signals.

    Args:
        llm_confidence:   Raw confidence from LLM (0.0–1.0)
        source:           Article source identifier
        severity:         Event severity ('low', 'medium', 'high')
        location:         Extracted location (None if missing)
        location_inferred: True if location was inferred, not direct
        age_label:        Human-readable age ('2h ago', '3d ago', etc.)
        is_recent:        True if article is within recency window
        confirmed_by_multiple_sources: True if same event seen in 2+ sources

    Returns:
        Enhanced confidence score clipped to [0.0, 1.0]
    """
    src_score = SOURCE_RELIABILITY.get(source, DEFAULT_SOURCE_RELIABILITY)
    sev_bonus = SEVERITY_BONUS.get(severity.lower(), 0.0)

    # Location bonus
    if location and not location_inferred:
        loc_bonus = 0.10
    elif location and location_inferred:
        loc_bonus = 0.05
    else:
        loc_bonus = 0.00

    # Recency bonus
    if age_label in ("now", "unknown date"):
        time_bonus = 0.07
    elif is_recent:
        from llm.filter import parse_age_label_to_hours
        hours = parse_age_label_to_hours(age_label)
        if hours is not None:
            if hours <= 1:
                time_bonus = 0.07
            elif hours <= 6:
                time_bonus = 0.05
            elif hours <= 24:
                time_bonus = 0.03
            else:
                time_bonus = 0.01
        else:
            time_bonus = 0.03
    else:
        time_bonus = 0.00

    multi_bonus = 0.05 if confirmed_by_multiple_sources else 0.00

    enhanced = (
        W_LLM    * llm_confidence
        + W_SOURCE * src_score
        + W_SEV    * (sev_bonus / 0.08 if sev_bonus > 0 else 0.0)
        + W_LOC    * (loc_bonus / 0.10 if loc_bonus > 0 else 0.0)
        + W_TIME   * (time_bonus / 0.07 if time_bonus > 0 else 0.0)
        + multi_bonus
    )

    return round(max(0.0, min(1.0, enhanced)), 4)


def compute_multi_source_confirmation(results: list[dict]) -> dict[str, bool]:
    """
    Detect events confirmed by multiple independent sources.

    Two events confirm each other if they share the same event_type,
    have overlapping locations, and come from different source categories.

    Args:
        results: List of extracted event result dicts

    Returns:
        Dict mapping str(index) → bool (True = confirmed by another source)
    """
    _OFFICIAL_APIS = {"tomtom_traffic", "here_traffic"}
    _OFFICIAL_GOV  = {
        "kolkata_police_advisory", "kolkata_police_vip", "kolkata_police_rally",
        "kolkata_police_scrape", "kmrc_scrape", "kmrc_news",
        "wb_disaster_scrape", "wb_disaster_news",
        "indian_railways_news", "eastern_railway_news", "kmc_waterlogging",
    }
    _NEWS    = {"rss", "rss_city", "newsapi"}
    _WEATHER = {"openweathermap", "openweathermap_alert"}

    def _cat(src: str) -> str:
        if src in _OFFICIAL_APIS:  return "api"
        if src in _OFFICIAL_GOV:   return "gov"
        if src in _NEWS:           return "news"
        if src in _WEATHER:        return "weather"
        return "other"

    def _overlap(loc_a: str, loc_b: str) -> bool:
        if not loc_a or not loc_b:
            return False
        a, b = loc_a.lower(), loc_b.lower()
        for word in a.split():
            if len(word) >= 4 and word in b:
                return True
        return False

    confirmed = {str(i): False for i in range(len(results))}

    for i, r1 in enumerate(results):
        for j, r2 in enumerate(results):
            if i >= j:
                continue
            if r1.get("event_type") != r2.get("event_type"):
                continue
            if _cat(r1.get("source", "")) == _cat(r2.get("source", "")):
                continue
            loc1 = (r1.get("location") or r1.get("road_name") or "")
            loc2 = (r2.get("location") or r2.get("road_name") or "")
            if _overlap(loc1, loc2):
                confirmed[str(i)] = True
                confirmed[str(j)] = True

    return confirmed
