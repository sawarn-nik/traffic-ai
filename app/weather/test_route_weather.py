from weather.route_sampler import sample_route_points
from weather.route_weather import fetch_weather
from weather.weather_risk import compute_weather_risk


# Dummy route

route_coords = [
    (22.5726,88.3639),
    (22.5800,88.3700),
    (22.5900,88.3800),
    (22.6000,88.3900),
    (22.6100,88.4000),
    (22.6200,88.4100),
]


sampled = sample_route_points(route_coords)

print("\nSampled Points:")
print(sampled)

total_wsi = 0

for idx,(lat,lon) in enumerate(sampled):

    weather = fetch_weather(lat,lon)

    risk = compute_weather_risk(weather)

    total_wsi += risk["wsi"]

    print(f"\nPoint {idx+1}")

    print(weather)

    print(risk)

avg_wsi = total_wsi / len(sampled)

print("\nAverage Route WSI:",round(avg_wsi,2))