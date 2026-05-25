from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from preprocess import PreprocessedGTFS


@dataclass
class Station:
    id: str
    name: str
    line: str
    lat: float
    lon: float
    routes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Connection:
    from_station: str
    to_station: str
    route_id: str
    route_short_name: str
    trip_id: str
    service_id: str
    departure_time: int
    arrival_time: int
    duration: int


@dataclass(frozen=True)
class Transfer:
    from_station: str
    to_station: str
    min_transfer_time: int


class Graph:
    def __init__(self):
        self.stations: dict[str, Station] = {}
        self.adjacency: dict[str, list[tuple[str, int]]] = {}
        self.schedule: dict[tuple[str, str], list[int]] = {}
        self.transfers: dict[tuple[str, str], int] = {}
        self.station_transfer_times: dict[str, int] = {}
        self.edge_route_short_names: dict[tuple[str, str], str] = {}
        self.route_colors: dict[str, str] = {}

    def add_station(self, s: Station):
        self.stations[s.id] = s
        self.adjacency.setdefault(s.id, [])

    def add_edge(self, a: str, b: str, duration: int):
        self.adjacency[a].append((b, duration))
        self.adjacency[b].append((a, duration))

    def add_departure(self, stop_from: str, stop_to: str, time_sec: int):
        key = (stop_from, stop_to)
        self.schedule.setdefault(key, []).append(time_sec)

    def sort_schedules(self):
        for key in self.schedule:
            self.schedule[key].sort()

    def next_departure(self, stop_from: str, stop_to: str, current_time: int) -> Optional[int]:
        """Retourne l'heure du prochain départ >= current_time, ou None."""
        import bisect
        times = self.schedule.get((stop_from, stop_to), [])
        idx = bisect.bisect_left(times, current_time)
        return times[idx] if idx < len(times) else None

    @classmethod
    def from_preprocessed(cls, data: PreprocessedGTFS) -> "Graph":
        g = cls()
        route_short_names = {route_id: route.route_short_name for route_id, route in data.routes.items()}
        g.route_colors = {
            route.route_short_name: f"#{route.route_color}" if route.route_color else "#888888"
            for route in data.routes.values()
        }

        station_routes: dict[str, set[str]] = {station_id: set() for station_id in data.stations}
        pair_durations: dict[tuple[str, str], list[int]] = defaultdict(list)
        pair_route_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        trip_connections: dict[str, list[Connection]] = defaultdict(list)
        route_station_sequences: dict[tuple[str, str], list[list[str]]] = defaultdict(list)
        shadowed_pairs: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        station_transfer_samples: dict[str, list[int]] = defaultdict(list)
        station_ids = set(data.stations) | set(data.stop_to_station.values())

        def get_station_fallback(station_id: str) -> tuple[str, float, float]:
            station_group = data.stations.get(station_id)
            if station_group is not None:
                return station_group.name, station_group.lat, station_group.lon

            for stop_id, mapped_station_id in data.stop_to_station.items():
                if mapped_station_id != station_id:
                    continue
                stop = data.stops.get(stop_id)
                if stop is not None:
                    return stop.name, stop.lat, stop.lon

            return station_id, 0.0, 0.0

        for station_id in station_ids:
            name, lat, lon = get_station_fallback(station_id)
            g.add_station(
                Station(
                    id=station_id,
                    name=name,
                    line="",
                    lat=lat,
                    lon=lon,
                )
            )

        for connection in data.connections:
            trip_connections[connection.trip_id].append(connection)

        for trip_id, connections in trip_connections.items():
            trip = data.trips.get(trip_id)
            if trip is None:
                continue

            ordered_connections = sorted(
                connections,
                key=lambda connection: (
                    connection.from_stop_sequence,
                    connection.to_stop_sequence,
                    connection.departure_time,
                    connection.arrival_time,
                ),
            )

            station_sequence: list[str] = []
            for connection in ordered_connections:
                from_station = data.stop_to_station.get(connection.from_stop_id)
                to_station = data.stop_to_station.get(connection.to_stop_id)
                if not from_station or not to_station:
                    continue
                if not station_sequence:
                    station_sequence.append(from_station)
                elif station_sequence[-1] != from_station:
                    station_sequence.append(from_station)
                if station_sequence[-1] != to_station:
                    station_sequence.append(to_station)

            if len(station_sequence) < 2:
                continue

            route_direction_key = (trip.route_id, str(trip.direction_id or ""))
            route_station_sequences[route_direction_key].append(station_sequence)

        for route_direction_key, sequences in route_station_sequences.items():
            for station_sequence in sequences:
                sequence_length = len(station_sequence)
                for start_index in range(sequence_length):
                    start_station = station_sequence[start_index]
                    for end_index in range(start_index + 2, sequence_length):
                        end_station = station_sequence[end_index]
                        shadowed_pairs[route_direction_key].add((min(start_station, end_station), max(start_station, end_station)))

        for connection in data.connections:
            from_station = data.stop_to_station.get(connection.from_stop_id)
            to_station = data.stop_to_station.get(connection.to_stop_id)
            if not from_station or not to_station or from_station == to_station:
                continue

            trip = data.trips.get(connection.trip_id)
            if trip is not None:
                blocked_pairs = shadowed_pairs.get((trip.route_id, str(trip.direction_id or "")))
                if blocked_pairs is not None:
                    canonical_pair = (min(from_station, to_station), max(from_station, to_station))
                    if canonical_pair in blocked_pairs:
                        continue

            route_short_name = route_short_names.get(connection.route_id, connection.route_id)
            directed_key = (from_station, to_station)
            canonical_key = (min(from_station, to_station), max(from_station, to_station))

            g.schedule.setdefault(directed_key, []).append(connection.departure_time)
            station_routes.setdefault(from_station, set()).add(route_short_name)
            station_routes.setdefault(to_station, set()).add(route_short_name)
            pair_durations[canonical_key].append(connection.duration)
            pair_route_counts[canonical_key][route_short_name] += 1

        for key in g.schedule:
            g.schedule[key].sort()

        for (a, b), durations in pair_durations.items():
            if a not in g.stations or b not in g.stations:
                continue
            duration = int(median(durations))
            g.add_edge(a, b, duration)
            dominant_route_short_name = pair_route_counts[(a, b)].most_common(1)[0][0]
            g.edge_route_short_names[(a, b)] = dominant_route_short_name
            g.edge_route_short_names[(b, a)] = dominant_route_short_name

        for station_id, station in list(g.stations.items()):
            routes = tuple(sorted(station_routes.get(station_id, set())))
            primary_line = routes[0] if routes else ""
            g.stations[station_id] = Station(
                id=station.id,
                name=station.name,
                line=primary_line,
                lat=station.lat,
                lon=station.lon,
                routes=routes,
            )

        for transfer in data.transfers:
            from_station = data.stop_to_station.get(transfer.from_stop_id)
            to_station = data.stop_to_station.get(transfer.to_stop_id)
            if not from_station or not to_station or from_station == to_station:
                if from_station and from_station == to_station:
                    station_transfer_samples[from_station].append(transfer.min_transfer_time)
                continue
            g.transfers[(from_station, to_station)] = transfer.min_transfer_time

        for station_id, samples in station_transfer_samples.items():
            g.station_transfer_times[station_id] = int(median(samples))

        return g
