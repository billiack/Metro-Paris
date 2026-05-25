from collections import deque
import heapq
from graph.models import Graph


def is_connected(g: Graph) -> tuple[bool, list[str]]:
    if not g.stations:
        return False, []
    start = next(iter(g.stations))
    visited = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        for voisin, _ in g.adjacency[node]:
            if voisin not in visited:
                queue.append(voisin)
    non_atteints = [s for s in g.stations if s not in visited]
    return len(non_atteints) == 0, non_atteints


def kruskal(g: Graph) -> tuple[list[tuple[str, str, int]], int]:
    parent = {s: s for s in g.stations}
    rank = {s: 0 for s in g.stations}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx == ry:
            return False
        if rank[rx] < rank[ry]:
            rx, ry = ry, rx
        parent[ry] = rx
        if rank[rx] == rank[ry]:
            rank[rx] += 1
        return True

    seen, edges = set(), []
    for na, voisins in g.adjacency.items():
        for nb, duree in voisins:
            key = (min(na, nb), max(na, nb))
            if key not in seen:
                seen.add(key)
                edges.append((duree, na, nb))
    edges.sort()

    acpm, poids_total = [], 0
    for duree, na, nb in edges:
        if union(na, nb):
            acpm.append((na, nb, duree))
            poids_total += duree
            if len(acpm) == len(g.stations) - 1:
                break
    return acpm, poids_total


def dijkstra_v3(g: Graph, start_id: str, end_id: str, departure_time: int) -> tuple[list[str], int, list[dict]]:
    transfer_adj: dict[str, list[tuple[str, int]]] = {}
    for (a, b), tf in g.transfers.items():
        transfer_adj.setdefault(a, []).append((b, tf))

    INF = float('inf')
    start_state = (start_id, None)
    time_at: dict[tuple[str, str | None], int] = {start_state: departure_time}
    prev: dict[tuple[str, str | None], tuple[tuple[str, str | None], int, str]] = {}
    pq = [(departure_time, start_state)]

    while pq:
        t, state = heapq.heappop(pq)
        if t > time_at[state]:
            continue
        u, last_route = state
        if u == end_id:
            break
        for v, dur in g.adjacency[u]:
            route_short_name = g.edge_route_short_names.get((u, v), g.edge_route_short_names.get((v, u), g.stations[u].line))
            transfer_time = g.station_transfer_times.get(u, 0) if last_route and last_route != route_short_name else 0
            ready_time = t + transfer_time
            next_dep = g.next_departure(u, v, ready_time)
            if next_dep is None:
                continue
            arr = next_dep + dur
            next_state = (v, route_short_name)
            if arr < time_at.get(next_state, INF):
                time_at[next_state] = arr
                prev[next_state] = (state, next_dep, "ride")
                heapq.heappush(pq, (arr, next_state))
        for v, tf in transfer_adj.get(u, []):
            arr = t + tf
            next_state = (v, last_route)
            if arr < time_at.get(next_state, INF):
                time_at[next_state] = arr
                prev[next_state] = (state, t, "transfer")
                heapq.heappush(pq, (arr, next_state))

    end_states = [(state, arrival) for state, arrival in time_at.items() if state[0] == end_id]
    if not end_states:
        return [], -1, []
    end_state, best_arrival = min(end_states, key=lambda item: item[1])

    path, details, cur = [], [], end_state
    while cur in prev:
        p, dep, kind = prev[cur]
        arrival = time_at[cur]
        if kind == "transfer":
            line = "Correspondance"
        else:
            line = cur[1] or g.stations[p[0]].line
        path.append(cur[0])
        details.append({
            'from_name': g.stations[p[0]].name,
            'to_name': g.stations[cur[0]].name,
            'line': line,
            'departure': dep,
            'arrival': arrival,
            'wait': max(0, arrival - time_at[p]) if kind == "transfer" else max(0, dep - time_at[p]),
            'kind': kind,
        })
        cur = p
    path.append(start_id)
    path.reverse()
    details.reverse()
    return path, best_arrival, details
