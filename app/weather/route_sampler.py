"""
route_sampler.py

Samples a route's coordinates so we don't call
OpenWeather for every node.

Example:
1000 route nodes
↓
5 sampled points
↓
5 API calls
"""

from typing import List, Tuple


def sample_route_points(
    coords: List[Tuple[float, float]],
    max_points: int = 5
) -> List[Tuple[float, float]]:
    """
    Sample evenly-spaced points along route.

    Args:
        coords: [(lat, lon), ...]
        max_points: maximum weather API calls

    Returns:
        sampled coordinates
    """

    if not coords:
        return []

    if len(coords) <= max_points:
        return coords

    step = len(coords) // (max_points - 1)

    sampled = []

    for i in range(0, len(coords), step):
        sampled.append(coords[i])

        if len(sampled) >= max_points - 1:
            break

    sampled.append(coords[-1])

    return sampled