import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load_stops():
    stops = {}

    with open(DATA_DIR / "stops.csv", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            stops[row["stop_id"]] = {
                "name": row["stop_name"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"])
            }

    return stops


def load_routes():

    routes = {}

    with open(DATA_DIR / "routes.csv", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            routes[row["route_id"]] = row

    return routes


def load_route_sequences():

    sequences = {}

    with open(DATA_DIR / "route_stop_sequence.csv", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            route_id = row["route_id"]

            sequences.setdefault(route_id, []).append(
                (
                    int(row["stop_sequence"]),
                    row["stop_id"]
                )
            )

    return sequences


def build_bus_graph():

    graph = {}

    sequences = load_route_sequences()

    for route_id, stops in sequences.items():

        stops.sort()

        for i in range(len(stops) - 1):

            current_stop = stops[i][1]
            next_stop = stops[i + 1][1]

            graph.setdefault(current_stop, []).append(next_stop)
            graph.setdefault(next_stop, []).append(current_stop)

    return graph


if __name__ == "__main__":

    graph = build_bus_graph()

    print("\nTotal Nodes:", len(graph))

    total_edges = sum(len(v) for v in graph.values()) // 2

    print("Total Edges:", total_edges)

    print("\nEsplanade Connections:")

    print(graph.get("S_ESPL"))