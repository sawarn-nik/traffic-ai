"""
impact_duration.py — Impact duration estimation for traffic events
==================================================================
Estimates how long a traffic disruption will last, producing:
  {
    start_time:           DD/MM/YY or "now"
    estimated_end_time:   natural language or DD/MM/YY
    impact_duration_mins: integer minutes
    impact_duration_label: human-readable string
  }

Priority:
  1. Official end time from API (TomTom endTime, etc.)
  2. LLM-estimated end time from schema
  3. Rule-based estimation by event type + severity
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from llm.filter import format_date_ddmmyy, format_today_ddmmyy


# ── Rule-based duration table ─────────────────────────────────────────────────
# (event_type, severity) → (min_mins, max_mins, label)

_DURATION_RULES: dict[tuple[str, str], tuple[int, int, str]] = {
    # Accidents
    ("accident",         "high"):   (120, 240, "2–4 hours"),
    ("accident",         "medium"): (60,  120, "1–2 hours"),
    ("accident",         "low"):    (30,  60,  "30–60 minutes"),
    # Congestion
    ("congestion",       "high"):   (90,  180, "1.5–3 hours"),
    ("congestion",       "medium"): (30,  90,  "30–90 minutes"),
    ("congestion",       "low"):    (15,  45,  "15–45 minutes"),
    # Road closure
    ("road_closure",     "high"):   (480, 1440, "8–24 hours"),
    ("road_closure",     "medium"): (120, 480,  "2–8 hours"),
    ("road_closure",     "low"):    (60,  240,  "1–4 hours"),
    # Construction
    ("construction",     "high"):   (10080, 43200, "1–4 weeks"),
    ("construction",     "medium"): (1440,  10080, "1–7 days"),
    ("construction",     "low"):    (240,   1440,  "4–24 hours"),
    # Waterlogging
    ("waterlogging",     "high"):   (360, 720, "6–12 hours"),
    ("waterlogging",     "medium"): (120, 360, "2–6 hours"),
    ("waterlogging",     "low"):    (60,  180, "1–3 hours"),
    # Weather
    ("weather",          "high"):   (360, 1440, "6–24 hours"),
    ("weather",          "medium"): (120, 360,  "2–6 hours"),
    ("weather",          "low"):    (60,  180,  "1–3 hours"),
    # VIP movement
    ("vip_movement",     "high"):   (60,  120, "1–2 hours"),
    ("vip_movement",     "medium"): (30,  60,  "30–60 minutes"),
    ("vip_movement",     "low"):    (15,  45,  "15–45 minutes"),
    # Protest / rally
    ("protest",          "high"):   (240, 480, "4–8 hours"),
    ("protest",          "medium"): (120, 240, "2–4 hours"),
    ("protest",          "low"):    (60,  120, "1–2 hours"),
    # Metro disruption
    ("metro_disruption", "high"):   (90,  240, "1.5–4 hours"),
    ("metro_disruption", "medium"): (30,  90,  "30–90 minutes"),
    ("metro_disruption", "low"):    (15,  45,  "15–45 minutes"),
    # Train delay
    ("train_delay",      "high"):   (120, 360, "2–6 hours"),
    ("train_delay",      "medium"): (60,  120, "1–2 hours"),
    ("train_delay",      "low"):    (30,  60,  "30–60 minutes"),
    # Transport strike
    ("transport_strike", "high"):   (480, 1440, "8–24 hours"),
    ("transport_strike", "medium"): (240, 480,  "4–8 hours"),
    ("transport_strike", "low"):    (120, 240,  "2–4 hours"),
    # Diversion
    ("diversion",        "high"):   (240, 480, "4–8 hours"),
    ("diversion",        "medium"): (60,  240, "1–4 hours"),
    ("diversion",        "low"):    (30,  120, "30 min–2 hours"),
}

# Default for unknown event types
_DEFAULT_DURATION = (60, 180, "1–3 hours")


def _midpoint(min_mins: int, max_mins: int) -> int:
    return (min_mins + max_mins) // 2


def _duration_label_from_mins(mins: int) -> str:
    """Convert minutes to a human-readable duration label."""
    if mins < 60:
        return f"~{mins} minutes"
    if mins < 120:
        return f"~{mins // 60} hour {mins % 60} min" if mins % 60 else "~1 hour"
    if mins < 1440:
        hours = mins / 60
        return f"~{hours:.0f} hours"
    if mins < 10080:
        days = mins / 1440
        return f"~{days:.0f} days"
    weeks = mins / 10080
    return f"~{weeks:.0f} weeks"


def _parse_tomtom_end_time(end_time_str: Optional[str]) -> Optional[str]:
    """
    Parse TomTom's endTime (ISO-8601) and return DD/MM/YY HH:MM format.
    Returns None if unparseable or None input.
    """
    if not end_time_str:
        return None
    try:
        dt = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        # Convert to IST (UTC+5:30) for display
        ist_offset = timedelta(hours=5, minutes=30)
        dt_ist = dt + ist_offset
        return dt_ist.strftime("%d/%m/%y %H:%M IST")
    except Exception:
        return None


def estimate_impact(
    event_type: str,
    severity: str,
    llm_estimated_end: Optional[str],
    llm_duration_mins: Optional[int],
    api_end_time: Optional[str],
    age_label: str,
) -> dict:
    """
    Estimate the impact duration for a traffic event.

    Priority:
      1. Official API end time (TomTom endTime)
      2. LLM-estimated end time from schema
      3. LLM-estimated duration in minutes
      4. Rule-based estimation

    Args:
        event_type:         Event type string
        severity:           Severity string
        llm_estimated_end:  LLM's estimated_end_time field
        llm_duration_mins:  LLM's impact_duration_mins field
        api_end_time:       Official end time from API (ISO string)
        age_label:          Article age label for start time display

    Returns:
        Dict with keys:
          start_time, estimated_end_time, impact_duration_mins,
          impact_duration_label, duration_source
    """
    today = format_today_ddmmyy()
    start_time = today if age_label in ("now", "unknown date") else (
        format_date_ddmmyy(age_label) or today
    )

    # ── 1. Official API end time ──────────────────────────────────────────────
    if api_end_time:
        parsed_end = _parse_tomtom_end_time(api_end_time)
        if parsed_end:
            # Estimate duration from now to end time
            try:
                dt_end = datetime.fromisoformat(api_end_time.replace("Z", "+00:00"))
                dt_now = datetime.now(tz=timezone.utc)
                remaining_mins = max(0, int((dt_end - dt_now).total_seconds() / 60))
                return {
                    "start_time":           start_time,
                    "estimated_end_time":   parsed_end,
                    "impact_duration_mins": remaining_mins,
                    "impact_duration_label": _duration_label_from_mins(remaining_mins),
                    "duration_source":      "api_official",
                }
            except Exception:
                pass

    # ── 2. LLM-estimated end time ─────────────────────────────────────────────
    if llm_estimated_end:
        # Try to parse as ISO, otherwise use as-is
        parsed = format_date_ddmmyy(llm_estimated_end)
        end_display = parsed or llm_estimated_end

        # Use LLM duration if available, else rule-based
        if llm_duration_mins and llm_duration_mins > 0:
            return {
                "start_time":           start_time,
                "estimated_end_time":   end_display,
                "impact_duration_mins": llm_duration_mins,
                "impact_duration_label": _duration_label_from_mins(llm_duration_mins),
                "duration_source":      "llm_estimated",
            }

    # ── 3. LLM duration only ──────────────────────────────────────────────────
    if llm_duration_mins and llm_duration_mins > 0:
        return {
            "start_time":           start_time,
            "estimated_end_time":   _duration_label_from_mins(llm_duration_mins) + " from now",
            "impact_duration_mins": llm_duration_mins,
            "impact_duration_label": _duration_label_from_mins(llm_duration_mins),
            "duration_source":      "llm_duration",
        }

    # ── 4. Rule-based estimation ──────────────────────────────────────────────
    key = (event_type.lower(), severity.lower())
    min_mins, max_mins, label = _DURATION_RULES.get(key, _DEFAULT_DURATION)
    mid = _midpoint(min_mins, max_mins)

    return {
        "start_time":           start_time,
        "estimated_end_time":   f"approx. {label} from now",
        "impact_duration_mins": mid,
        "impact_duration_label": label,
        "duration_source":      "rule_based",
    }
