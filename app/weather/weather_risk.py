"""
weather_risk.py

Convert OpenWeather data into
Weather Severity Index (WSI)
"""

def compute_weather_risk(weather: dict):

    rain = weather.get("rain_1h", 0)
    wind = weather.get("wind_speed", 0)
    vis = weather.get("visibility", 10000)

    rain_score = min(rain / 20, 1)
    wind_score = min(wind / 20, 1)
    vis_score = max(0, (10000 - vis) / 10000)

    wsi = (
        0.5 * rain_score +
        0.3 * wind_score +
        0.2 * vis_score
    )

    if wsi >= 0.7:
        severity = "high"

    elif wsi >= 0.3:
        severity = "medium"

    else:
        severity = "low"

    return {
        "wsi": round(wsi, 2),
        "severity": severity
    }