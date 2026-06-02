"""
weather_fetcher.py — OpenWeatherMap Current + Alerts for Kolkata
================================================================
Fetches real-time weather conditions and government-issued weather alerts
for Kolkata. Weather is a first-class disruption source in this project:
  - Monsoon rain (June–September) → waterlogging, road closures
  - Cyclones (Bay of Bengal) → city-wide shutdowns
  - Dense fog (December–January) → visibility-related accidents

OpenWeatherMap free tier: 1,000 calls/day — more than sufficient.
Get a free API key at: https://openweathermap.org/api  (no credit card needed)

Two endpoints used:
  1. /weather  — current conditions (rain, wind, visibility, temperature)
  2. /onecall  — government weather alerts (cyclone warnings, flood alerts)

Output is normalised into article-shaped dicts for the LLM pipeline.
"""

import requests
from datetime import datetime, timezone
from config import OPENWEATHER_API_KEY

# Kolkata coordinates
KOLKATA_LAT = 22.5726
KOLKATA_LON = 88.3639

OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"

# Rain intensity thresholds (mm/h) → disruption severity
# Based on IMD (India Meteorological Department) classification
_RAIN_SEVERITY = [
    (50.0, "high",   "Extremely heavy rain — severe waterlogging likely"),
    (15.0, "high",   "Very heavy rain — major waterlogging expected"),
    (7.5,  "medium", "Heavy rain — moderate waterlogging possible"),
    (2.5,  "medium", "Moderate rain — traffic slowdown expected"),
    (0.1,  "low",    "Light rain — minor traffic impact"),
]

# Wind speed thresholds (m/s) → disruption severity
_WIND_SEVERITY = [
    (20.0, "high",   "Cyclonic wind — road closures likely"),
    (13.0, "medium", "Strong wind — driving hazard"),
    (7.0,  "low",    "Moderate wind — minor impact"),
]

# Visibility thresholds (metres) → disruption severity
_VIS_SEVERITY = [
    (200,  "high",   "Dense fog — near-zero visibility, road closures likely"),
    (500,  "medium", "Thick fog — very low visibility, major slowdown"),
    (1000, "low",    "Foggy conditions — reduced visibility"),
]


def _assess_weather(data: dict) -> tuple[str, str, str]:
    """
    Assess weather severity from OWM current-weather response.

    Returns:
        (severity, event_type, reason) tuple
    """
    rain_1h  = data.get("rain", {}).get("1h", 0.0)
    wind_spd = data.get("wind", {}).get("speed", 0.0)
    vis      = data.get("visibility", 10000)
    weather  = data.get("weather", [{}])[0]
    main     = weather.get("main", "").lower()
    desc     = weather.get("description", "")

    # Check rain first (most common Kolkata disruption)
    for threshold, sev, reason in _RAIN_SEVERITY:
        if rain_1h >= threshold:
            return sev, "weather", reason

    # Check wind (cyclone season)
    for threshold, sev, reason in _WIND_SEVERITY:
        if wind_spd >= threshold:
            return sev, "weather", reason

    # Check visibility (fog season)
    for threshold, sev, reason in _VIS_SEVERITY:
        if vis <= threshold:
            return sev, "weather", reason

    # Thunderstorm / squall
    if "thunderstorm" in main or "squall" in main:
        return "medium", "weather", f"Thunderstorm — {desc}"

    # Snow (rare in Kolkata but handle it)
    if "snow" in main:
        return "medium", "weather", f"Snowfall — {desc}"

    return "low", "weather", f"Weather conditions: {desc}"


def fetch_weather_conditions(max_items: int = 3) -> list[dict]:
    """
    Fetch current weather conditions for Kolkata and convert to
    article-shaped dicts for the LLM pipeline.

    Only returns articles if weather conditions are disruptive
    (rain > 0.1mm/h, wind > 7m/s, or visibility < 1000m).

    Args:
        max_items: Maximum number of weather articles to return (usually 1–2).

    Returns:
        List of article-shaped dicts, empty if weather is benign.
    """
    if not OPENWEATHER_API_KEY:
        print("  [Weather] API key not set — skipping weather fetch")
        return []

    params = {
        "lat":   KOLKATA_LAT,
        "lon":   KOLKATA_LON,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
    }

    articles = []

    # ── 1. Current conditions ─────────────────────────────────────────────────
    try:
        print("  [Weather] Fetching current conditions for Kolkata ...")
        resp = requests.get(OWM_CURRENT_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        rain_1h  = data.get("rain", {}).get("1h", 0.0)
        wind_spd = data.get("wind", {}).get("speed", 0.0)
        vis      = data.get("visibility", 10000)
        temp     = data.get("main", {}).get("temp", 0)
        humidity = data.get("main", {}).get("humidity", 0)
        desc     = data.get("weather", [{}])[0].get("description", "clear")

        severity, event_type, reason = _assess_weather(data)

        # Only emit an article if conditions are actually disruptive
        is_disruptive = (
            rain_1h > 0.1
            or wind_spd > 7.0
            or vis < 1000
            or "thunderstorm" in desc.lower()
            or "squall" in desc.lower()
        )

        if is_disruptive:
            title = f"[Weather] Kolkata: {desc.title()} — {severity.upper()} disruption risk"
            description = (
                f"{reason}. "
                f"Rain: {rain_1h:.1f}mm/h, "
                f"Wind: {wind_spd:.1f}m/s, "
                f"Visibility: {vis}m, "
                f"Temp: {temp}°C, "
                f"Humidity: {humidity}%."
            )
            articles.append({
                "title":       title,
                "description": description,
                "url":         "owm://current/kolkata",
                "source":      "openweathermap",
                "age_label":   "now",
                "is_recent":   True,
                "_weather_severity": severity,
                "_weather_type":     event_type,
            })
            print(f"  [Weather] Disruptive conditions: {desc} | rain={rain_1h}mm/h | wind={wind_spd}m/s | vis={vis}m")
        else:
            print(f"  [Weather] Benign conditions: {desc} — no disruption article generated")

    except requests.exceptions.Timeout:
        print("  [Weather] Current conditions request timed out")
    except requests.exceptions.HTTPError as e:
        print(f"  [Weather] HTTP error (current): {e.response.status_code}")
    except Exception as e:
        print(f"  [Weather] Error fetching current conditions: {e}")

    # ── 2. Government weather alerts (OWM One Call API 3.0) ──────────────────
    try:
        onecall_params = {
            "lat":     KOLKATA_LAT,
            "lon":     KOLKATA_LON,
            "appid":   OPENWEATHER_API_KEY,
            "exclude": "minutely,hourly,daily",
            "units":   "metric",
        }
        resp = requests.get(OWM_ONECALL_URL, params=onecall_params, timeout=10)

        # One Call 3.0 requires a paid subscription — gracefully skip if 401
        if resp.status_code == 401:
            print("  [Weather] One Call API requires subscription — skipping alerts")
        elif resp.status_code == 200:
            alerts = resp.json().get("alerts", [])
            print(f"  [Weather] Got {len(alerts)} government weather alerts")
            for alert in alerts[:max_items]:
                sender      = alert.get("sender_name", "IMD")
                event_name  = alert.get("event", "Weather Alert")
                description = alert.get("description", "")
                start_ts    = alert.get("start", 0)
                end_ts      = alert.get("end", 0)

                start_str = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if start_ts else ""
                end_str   = datetime.fromtimestamp(end_ts,   tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if end_ts   else ""

                title = f"[Weather Alert] {event_name} — issued by {sender}"
                full_desc = description
                if start_str:
                    full_desc += f" | Valid: {start_str} to {end_str}"

                articles.append({
                    "title":       title,
                    "description": full_desc[:500],
                    "url":         f"owm://alert/{start_ts}",
                    "source":      "openweathermap_alert",
                    "age_label":   "now",
                    "is_recent":   True,
                    "_weather_severity": "high",
                    "_weather_type":     "weather",
                })
        else:
            print(f"  [Weather] One Call API returned {resp.status_code}")

    except Exception as e:
        print(f"  [Weather] Error fetching alerts: {e}")

    return articles
