from weather.route_weather import analyze_route_weather

coords = [
    (22.5726,88.3639),
    (22.58,88.37),
    (22.59,88.38),
    (22.60,88.39),
    (22.62,88.41),
]

result = analyze_route_weather(coords)

print(result)