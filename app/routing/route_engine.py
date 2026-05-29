"""
route_engine.py — OSMnx-based routing for Kolkata

Graph is downloaded once and cached to disk as a GraphML file so
subsequent runs don't re-download the full city network.

get_route() geocodes source/destination with Kolkata as the city
context so short locality names like "Park Street" or "Salt Lake"
resolve correctly without the user having to type the full address.
"""

import os
import osmnx as ox

from config import DEFAULT_CITY, GRAPH_CACHE_PATH


# ── Graph loader (cached) ─────────────────────────────────────────────────────

def _load_graph():
    """
    Load the Kolkata drive network.
    - First run  : downloads from OSM and saves to GRAPH_CACHE_PATH
    - Later runs : loads from the cached GraphML file (fast)
    """
    cache_path = GRAPH_CACHE_PATH

    if os.path.exists(cache_path):
        print(f"  [Route] Loading cached graph from {cache_path} ...")
        graph = ox.load_graphml(cache_path)
    else:
        print(f"  [Route] Downloading OSM graph for {DEFAULT_CITY} (one-time, ~30s) ...")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        graph = ox.graph_from_place(DEFAULT_CITY, network_type="drive")
        ox.save_graphml(graph, cache_path)
        print(f"  [Route] Graph cached to {cache_path}")

    return graph


# ── Geocoding with city context ───────────────────────────────────────────────

def _geocode_with_context(place: str) -> tuple[float, float]:
    """
    Geocode a place name, automatically appending ', Kolkata, India'
    if the query doesn't already mention Kolkata or India.

    This lets users type short names like:
        "Park Street"  →  "Park Street, Kolkata, India"
        "Salt Lake Sector V"  →  "Salt Lake Sector V, Kolkata, India"
        "Howrah Bridge"  →  "Howrah Bridge, Kolkata, India"
    """
    city_hint = DEFAULT_CITY  # "Kolkata, India"
    city_lower = place.lower()

    needs_hint = not any(
        kw in city_lower
        for kw in ("kolkata", "calcutta", "india", "west bengal", "wb")
    )

    query = f"{place}, {city_hint}" if needs_hint else place

    try:
        coords = ox.geocode(query)
        print(f"  [Route] Geocoded '{place}' → {coords}")
        return coords
    except Exception:
        # Retry without city hint in case the full string confuses the geocoder
        print(f"  [Route] Retrying geocode without city hint for '{place}' ...")
        coords = ox.geocode(place)
        print(f"  [Route] Geocoded '{place}' → {coords}")
        return coords


# ── Public API ────────────────────────────────────────────────────────────────

def get_route(source: str, destination: str):
    """
    Compute the shortest driving route between source and destination
    within the Kolkata road network.

    Args:
        source:      Origin locality / address (e.g. "Howrah Station")
        destination: Destination locality / address (e.g. "Salt Lake Sector V")

    Returns:
        (graph, route) — OSMnx MultiDiGraph and list of node IDs
    """
    graph = _load_graph()

    src_coords  = _geocode_with_context(source)
    dest_coords = _geocode_with_context(destination)

    src_node = ox.distance.nearest_nodes(
        graph,
        X=src_coords[1],   # longitude
        Y=src_coords[0],   # latitude
    )
    dest_node = ox.distance.nearest_nodes(
        graph,
        X=dest_coords[1],
        Y=dest_coords[0],
    )

    route = ox.shortest_path(graph, src_node, dest_node)

    if route is None:
        raise ValueError(
            f"No route found between '{source}' and '{destination}' "
            f"in the Kolkata road network. "
            "Try using a more specific address or a well-known landmark."
        )

    return graph, route


def extract_road_names(graph, route: list) -> list[str]:
    """
    Extract unique named road segments from a route.

    Returns a list of road names in the order they first appear,
    filtering out unnamed segments.
    """
    seen  = set()
    roads = []

    for u, v in zip(route[:-1], route[1:]):
        edge_data = graph.get_edge_data(u, v)
        if not edge_data:
            continue

        edge = list(edge_data.values())[0]
        name = edge.get("name")

        if not name:
            continue

        # OSMnx sometimes returns a list when multiple names exist
        names = name if isinstance(name, list) else [name]
        for n in names:
            if n and n not in seen:
                seen.add(n)
                roads.append(n)

    return roads
