from collections import deque

from bus_graph import build_bus_graph


def find_bus_path(source, destination):

    graph = build_bus_graph()

    queue = deque([[source]])

    visited = set()

    while queue:

        path = queue.popleft()

        node = path[-1]

        if node == destination:
            return path

        if node not in visited:

            visited.add(node)

            for neighbor in graph.get(node, []):

                new_path = list(path)
                new_path.append(neighbor)

                queue.append(new_path)

    return None


if __name__ == "__main__":

    source = "S_HWH"
    destination = "S_AIRPORT"

    path = find_bus_path(source, destination)

    print("\nRoute Found:\n")

    print(path)