"""
congestion_score.py — Severity scoring and route impact calculation
===================================================================
Provides:
  compute_score()         — severity label → numeric score (2/5/10)
  compute_weighted_score() — severity × confidence → weighted scalar
  compute_route_impact()  — full route impact score with breakdown
"""

from config import SEVERITY_SCORES, DEFAULT_SCORE


def compute_score(severity: str) -> int:
    """
    Map a severity label to a numeric congestion score.
      low    → 2
      medium → 5
      high   → 10
    """
    return SEVERITY_SCORES.get(severity.lower().strip(), DEFAULT_SCORE)


def compute_weighted_score(severity: str, confidence: float) -> float:
    """
    Weighted score = severity_score × confidence (κ).

    Directly usable as an input signal for the Bayesian fusion layer (Layer 2).

    Example:
        severity="high",   confidence=0.9  →  10 × 0.9 = 9.0
        severity="medium", confidence=0.4  →   5 × 0.4 = 2.0
    """
    base = compute_score(severity)
    return round(base * max(0.0, min(1.0, confidence)), 4)


def compute_route_impact(results: list[dict]) -> dict:
    """
    Compute a comprehensive route impact score from all extracted events.

    The route impact score combines:
      - Weighted severity × confidence for each event
      - Recency bonus (recent events count more)
      - Duration penalty (longer disruptions = higher impact)
      - Source reliability weighting

    Returns a dict with:
      total_score:      Overall route impact (0–100 scale)
      recent_score:     Impact from recent events only
      active_score:     Impact from currently active (non-future) events
      future_score:     Impact from planned/future events
      risk_level:       "LOW" / "MODERATE" / "HIGH" / "CRITICAL"
      risk_label:       Human-readable risk description
      breakdown:        Per-severity counts and scores
      recommendation:   Actionable advice for the traveller
    """
    if not results:
        return {
            "total_score":   0.0,
            "recent_score":  0.0,
            "active_score":  0.0,
            "future_score":  0.0,
            "risk_level":    "LOW",
            "risk_label":    "No disruptions detected",
            "breakdown":     {"high": 0, "medium": 0, "low": 0},
            "recommendation": "Route appears clear. Proceed normally.",
        }

    recent_results = [r for r in results if r.get("is_recent", True)]
    active_results = [r for r in recent_results if not r.get("is_future_event", False)]
    future_results = [r for r in recent_results if r.get("is_future_event", False)]

    def _event_impact(r: dict) -> float:
        """Compute impact score for a single event."""
        base = compute_weighted_score(r.get("severity", "low"), r.get("confidence", 0.5))

        # Duration multiplier: longer disruptions = higher impact
        dur_mins = r.get("impact_duration_mins") or 60
        if dur_mins >= 1440:    dur_mult = 2.0   # 1+ day
        elif dur_mins >= 480:   dur_mult = 1.5   # 8+ hours
        elif dur_mins >= 120:   dur_mult = 1.2   # 2+ hours
        else:                   dur_mult = 1.0

        # Recency multiplier
        age_label = r.get("age_label", "unknown date")
        if age_label in ("now", "unknown date"):
            rec_mult = 1.0
        else:
            from llm.filter import parse_age_label_to_hours
            hours = parse_age_label_to_hours(age_label) or 24
            if hours <= 1:    rec_mult = 1.0
            elif hours <= 6:  rec_mult = 0.9
            elif hours <= 24: rec_mult = 0.75
            else:             rec_mult = 0.5

        return round(base * dur_mult * rec_mult, 4)

    total_score  = sum(_event_impact(r) for r in results)
    recent_score = sum(_event_impact(r) for r in recent_results)
    active_score = sum(_event_impact(r) for r in active_results)
    future_score = sum(_event_impact(r) for r in future_results)

    # Breakdown by severity (recent events only)
    breakdown = {
        "high":   sum(1 for r in recent_results if r.get("severity") == "high"),
        "medium": sum(1 for r in recent_results if r.get("severity") == "medium"),
        "low":    sum(1 for r in recent_results if r.get("severity") == "low"),
    }

    # Risk level thresholds (tuned for typical Kolkata route)
    if active_score >= 25 or breakdown["high"] >= 3:
        risk_level = "CRITICAL"
        risk_label = "Severe disruptions — route heavily affected"
        recommendation = (
            "⛔ CRITICAL RISK — Multiple severe disruptions on your route. "
            "Strongly consider an alternative route or delay your journey."
        )
    elif active_score >= 12 or breakdown["high"] >= 1:
        risk_level = "HIGH"
        risk_label = "Significant disruptions on route"
        recommendation = (
            "⚠ HIGH RISK — Significant disruptions detected. "
            "Consider an alternative route or allow extra travel time (30–60 min)."
        )
    elif active_score >= 5 or breakdown["medium"] >= 2:
        risk_level = "MODERATE"
        risk_label = "Moderate disruptions — expect delays"
        recommendation = (
            "⚡ MODERATE RISK — Some disruptions on your route. "
            "Allow 15–30 minutes extra travel time."
        )
    elif active_score > 0:
        risk_level = "LOW"
        risk_label = "Minor disruptions — minimal impact"
        recommendation = (
            "✓ LOW RISK — Minor disruptions only. "
            "Route is mostly clear; allow a few extra minutes."
        )
    else:
        risk_level = "CLEAR"
        risk_label = "No active disruptions detected"
        recommendation = "✓ CLEAR — No disruptions detected. Proceed normally."

    return {
        "total_score":   round(total_score, 2),
        "recent_score":  round(recent_score, 2),
        "active_score":  round(active_score, 2),
        "future_score":  round(future_score, 2),
        "risk_level":    risk_level,
        "risk_label":    risk_label,
        "breakdown":     breakdown,
        "recommendation": recommendation,
    }


def compare_routes(route_profiles: list[dict]) -> list[dict]:
    """
    Rank a list of route profiles by their active impact score (ascending).

    Each profile is expected to contain at least:
        route_id, route_label, distance_km, travel_time_min,
        route_results, citywide_results, impact (from compute_route_impact)

    Returns the same list sorted so the best (lowest active impact) route
    comes first. Ties are broken by distance_km (shorter is better).
    """
    if not route_profiles:
        return []

    return sorted(
        route_profiles,
        key=lambda r: (
            r["impact"]["active_score"],   # primary: fewest active disruptions
            r["impact"]["future_score"],   # secondary: fewest future disruptions
            r.get("distance_km", 0),       # tertiary: shorter distance
        ),
    )
