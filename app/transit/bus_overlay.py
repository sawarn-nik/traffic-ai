from bus_graph import load_stops


def get_path_coordinates(path):

    stops = load_stops()

    coordinates = []

    for stop_id in path:

        if stop_id in stops:

            coordinates.append([
                stops[stop_id]["lat"],
                stops[stop_id]["lon"]
            ])

    return coordinates


if __name__ == "__main__":

    sample_path = [
        "S_HWH",
        "S_BBDBAG",
        "S_CENTRAL",
        "S_GIRISHPARK"
    ]

    print(get_path_coordinates(sample_path))