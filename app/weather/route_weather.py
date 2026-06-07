"""
route_weather.py

Fetch weather for sampled route points and compute
route-level weather risk profile.
"""

import requests

from config import OPENWEATHER_API_KEY
from weather.route_sampler import sample_route_points
from weather.weather_risk import compute_weather_risk


OWM_URL = "https://api.openweathermap.org/data/2.5/weather"


def fetch_weather(lat: float, lon: float) -> dict:
    """
    Fetch current weather at a coordinate.
    """

    params = {
        "lat": lat,
        "lon": lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    }

    try:
        response = requests.get(
            OWM_URL,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

        return {
            "lat": lat,
            "lon": lon,
            "temp": data.get("main", {}).get("temp"),
            "humidity": data.get("main", {}).get("humidity"),
            "visibility": data.get("visibility", 10000),
            "wind_speed": data.get("wind", {}).get("speed", 0),
            "rain_1h": data.get("rain", {}).get("1h", 0),
            "condition": data.get("weather", [{}])[0].get("main", "")
        }

    except Exception as e:
        print(f"[Weather] Error at ({lat}, {lon}): {e}")
        return {}


def analyze_route_weather(route_coords):
    """
    Analyze weather along an entire route.

    Returns:
    {
        avg_wsi,
        max_wsi,
        severity,
        sample_points,
        weather_points,
        success
    }
    """

    sampled_points = sample_route_points(route_coords)

    weather_points = []
    wsi_values = []

    for lat, lon in sampled_points:

        weather = fetch_weather(lat, lon)

        if not weather:
            continue

        risk = compute_weather_risk(weather)

        wsi_values.append(risk["wsi"])

        weather_points.append({
            "lat": lat,
            "lon": lon,
            "weather": weather,
            "risk": risk
        })

    # All API calls failed
    if not weather_points:
        return {
            "avg_wsi": None,
            "max_wsi": None,
            "severity": "unknown",
            "sample_points": 0,
            "weather_points": [],
            "success": False
        }

    avg_wsi = sum(wsi_values) / len(wsi_values)
    max_wsi = max(wsi_values)

    # Severity based on average route risk
    if avg_wsi >= 0.70:
        severity = "high"

    elif avg_wsi >= 0.30:
        severity = "medium"

    else:
        severity = "low"

    return {
        "avg_wsi": round(avg_wsi, 2),
        "max_wsi": round(max_wsi, 2),
        "severity": severity,
        "sample_points": len(weather_points),
        "weather_points": weather_points,
        "success": True
    }