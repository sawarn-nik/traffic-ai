import json
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data"


def load_bus_stops():
    """
    Load bus stops from JSON.
    """

    file_path = DATA_DIR / "bus_stops.json"

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data

def load_bus_routes():
    """
    Load bus routes from JSON.
    """

    file_path = DATA_DIR / "bus_routes.json"

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data

if __name__ == "__main__":
    print("Stops:")
    print(load_bus_stops())

    print("\nRoutes:")
    print(load_bus_routes())