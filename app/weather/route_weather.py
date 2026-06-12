"""
route_weather.py

Fetch current weather at a coordinate from OpenWeatherMap.

Used by api.py → _fetch_city_weather() to get a single
city-wide weather sample (not per-route — weather is city-wide).
"""

import requests
from config import OPENWEATHER_API_KEY

OWM_URL = "https://api.openweathermap.org/data/2.5/weather"


def fetch_weather(lat: float, lon: float) -> dict:
    """
    Fetch current weather at a coordinate.

    Returns a dict with keys:
        lat, lon, temp, humidity, visibility,
        wind_speed, rain_1h, condition
    Returns empty dict on failure.
    """
    params = {
        "lat":   lat,
        "lon":   lon,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
    }
    try:
        resp = requests.get(OWM_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "lat":        lat,
            "lon":        lon,
            "temp":       data.get("main", {}).get("temp"),
            "humidity":   data.get("main", {}).get("humidity"),
            "visibility": data.get("visibility", 10000),
            "wind_speed": data.get("wind", {}).get("speed", 0),
            "rain_1h":    data.get("rain", {}).get("1h", 0),
            "condition":  data.get("weather", [{}])[0].get("main", ""),
        }
    except Exception as e:
        print(f"[Weather] Error at ({lat}, {lon}): {e}")
        return {}
