from __future__ import annotations
import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import gzip
from typing import Any



METRO_TYPE = "1" # Type métro
KEPT_ROUTE_TYPES = {"1", "2"} # Prend les métros (1) et RER (2) (hors TER)
RER_NAMES = {"A", "B", "C", "D", "E"}
TER_PREFIX = "TER"


def time_to_seconds(value: str) -> int:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip() == "1"


def _maybe_int(value: str | None) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


def _is_kept_route(row: dict[str, str], route_types: set[str]) -> bool:
    """
    Détermine si une route doit être conservée en fonction de son type et de ses attributs.
    """
    route_type = row.get("route_type", "").strip()
    if route_type not in route_types:
        return False

    if route_type != "2":
        return True

    short_name = row.get("route_short_name", "").strip().upper()
    long_name = (row.get("route_long_name") or "").strip().upper()
    desc = (row.get("route_desc") or "").strip().upper()

    if short_name.startswith(TER_PREFIX) or long_name.startswith(TER_PREFIX) or desc.startswith(TER_PREFIX):
        return False

    return bool(short_name) and short_name[0] in RER_NAMES


@dataclass(frozen=True)
class RouteInfo:
    """
    Représente les informations sur une route GTFS. 
    """
    route_id: str
    route_short_name: str
    route_long_name: str | None = None
    route_type: str = METRO_TYPE
    route_color: str | None = None
    route_text_color: str | None = None


@dataclass(frozen=True)
class ServiceCalendar:
    """
    Représente le calendrier de service d'une route GTFS, incluant les jours de la semaine et les exceptions.
    """
    service_id: str
    start_date: str | None = None
    end_date: str | None = None
    monday: bool = False
    tuesday: bool = False
    wednesday: bool = False
    thursday: bool = False
    friday: bool = False
    saturday: bool = False
    sunday: bool = False
    added_dates: list[str] = field(default_factory=list)
    removed_dates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StopInfo:
    """
    Représente les informations sur un arrêt GTFS, y compris son ID, son nom, sa position géographique et ses relations avec les stations.  
    """
    stop_id: str
    name: str
    lat: float
    lon: float
    parent_station: str | None = None
    location_type: str | None = None
    platform_code: str | None = None
    wheelchair_boarding: str | None = None


@dataclass(frozen=True)
class StationGroup:
    """
    Représente un groupe de stations GTFS, qui peut correspondre à une station physique avec plusieurs arrêts (platform stops). 
    """
    station_id: str
    name: str
    lat: float
    lon: float
    platform_stop_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TripInfo:
    """
    Représente les informations sur un voyage GTFS, y compris son ID, la route associée, le service et d'autres métadonnées.
    """
    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: str | None = None
    direction_id: str | None = None
    block_id: str | None = None
    shape_id: str | None = None


@dataclass(frozen=True)
class TimetableConnection:
    """
    Représente une connexion dans le tableau de bord horaire, reliant deux arrêts pour un voyage spécifique.
    """
    trip_id: str
    route_id: str
    service_id: str
    from_stop_id: str
    to_stop_id: str
    from_stop_sequence: int
    to_stop_sequence: int
    departure_time: int
    arrival_time: int
    duration: int


@dataclass(frozen=True)
class TransferInfo:
    """
    Représente les informations sur un transfert entre deux arrêts, y compris les temps de transfert et les routes associées.
    """
    from_stop_id: str
    to_stop_id: str
    min_transfer_time: int
    transfer_type: str | None = None
    from_route_id: str | None = None
    to_route_id: str | None = None


@dataclass
class PreprocessedGTFS:
    """
    Représente les données GTFS prétraitées, incluant les routes, les services, les stations, les arrêts, les voyages, les connexions et les transferts.
"""
    source_dir: str
    generated_at: str
    routes: dict[str, RouteInfo]
    services: dict[str, ServiceCalendar]
    stations: dict[str, StationGroup]
    stops: dict[str, StopInfo]
    trips: dict[str, TripInfo]
    connections: list[TimetableConnection]
    transfers: list[TransferInfo]
    stop_to_station: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dir": self.source_dir,
            "generated_at": self.generated_at,
            "routes": {
                key: {
                    "route_id": value.route_id,
                    "route_short_name": value.route_short_name,
                    "route_color": value.route_color,
                }
                for key, value in self.routes.items()
            },
            "stations": {
                key: {
                    "station_id": value.station_id,
                    "name": value.name,
                    "lat": value.lat,
                    "lon": value.lon,
                }
                for key, value in self.stations.items()
            },
            "stops": {
                key: {
                    "stop_id": value.stop_id,
                    "name": value.name,
                    "lat": value.lat,
                    "lon": value.lon,
                    "parent_station": value.parent_station,
                }
                for key, value in self.stops.items()
            },
            "trips": {
                key: {
                    "trip_id": value.trip_id,
                    "route_id": value.route_id,
                    "direction_id": value.direction_id,
                }
                for key, value in self.trips.items()
            },
            "connections": [
                {
                    "trip_id": value.trip_id,
                    "route_id": value.route_id,
                    "from_stop_id": value.from_stop_id,
                    "to_stop_id": value.to_stop_id,
                    "from_stop_sequence": value.from_stop_sequence,
                    "to_stop_sequence": value.to_stop_sequence,
                    "departure_time": value.departure_time,
                    "arrival_time": value.arrival_time,
                    "duration": value.duration,
                }
                for value in self.connections
            ],
            "transfers": [
                {
                    "from_stop_id": value.from_stop_id,
                    "to_stop_id": value.to_stop_id,
                    "min_transfer_time": value.min_transfer_time,
                }
                for value in self.transfers
            ],
            "stop_to_station": dict(self.stop_to_station),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreprocessedGTFS":
        routes = {
            key: RouteInfo(
                route_id=value["route_id"],
                route_short_name=value["route_short_name"],
                route_long_name=value.get("route_long_name"),
                route_type=value.get("route_type", METRO_TYPE),
                route_color=value.get("route_color"),
                route_text_color=value.get("route_text_color"),
            )
            for key, value in data.get("routes", {}).items()
        }

        stations = {
            key: StationGroup(
                station_id=value["station_id"],
                name=value["name"],
                lat=value["lat"],
                lon=value["lon"],
                platform_stop_ids=list(value.get("platform_stop_ids", [])),
            )
            for key, value in data.get("stations", {}).items()
        }

        stops = {
            key: StopInfo(
                stop_id=value["stop_id"],
                name=value["name"],
                lat=value["lat"],
                lon=value["lon"],
                parent_station=value.get("parent_station"),
                location_type=value.get("location_type"),
                platform_code=value.get("platform_code"),
                wheelchair_boarding=value.get("wheelchair_boarding"),
            )
            for key, value in data.get("stops", {}).items()
        }

        trips = {
            key: TripInfo(
                trip_id=value["trip_id"],
                route_id=value["route_id"],
                service_id=value.get("service_id", ""),
                trip_headsign=value.get("trip_headsign"),
                direction_id=value.get("direction_id"),
                block_id=value.get("block_id"),
                shape_id=value.get("shape_id"),
            )
            for key, value in data.get("trips", {}).items()
        }

        connections = [
            TimetableConnection(
                trip_id=value["trip_id"],
                route_id=value["route_id"],
                service_id=value.get("service_id", ""),
                from_stop_id=value["from_stop_id"],
                to_stop_id=value["to_stop_id"],
                from_stop_sequence=value["from_stop_sequence"],
                to_stop_sequence=value["to_stop_sequence"],
                departure_time=value["departure_time"],
                arrival_time=value["arrival_time"],
                duration=value["duration"],
            )
            for value in data.get("connections", [])
        ]

        transfers = [
            TransferInfo(
                from_stop_id=value["from_stop_id"],
                to_stop_id=value["to_stop_id"],
                min_transfer_time=value["min_transfer_time"],
                transfer_type=value.get("transfer_type"),
                from_route_id=value.get("from_route_id"),
                to_route_id=value.get("to_route_id"),
            )
            for value in data.get("transfers", [])
        ]

        return cls(
            source_dir=data.get("source_dir", ""),
            generated_at=data.get("generated_at", ""),
            routes=routes,
            services={key: ServiceCalendar(**value) for key, value in data.get("services", {}).items()},
            stations=stations,
            stops=stops,
            trips=trips,
            connections=connections,
            transfers=transfers,
            stop_to_station=dict(data.get("stop_to_station", {})),
        )


def preprocess_gtfs(data_dir: str, route_types: set[str] = KEPT_ROUTE_TYPES) -> PreprocessedGTFS:
    base = Path(data_dir)

    # Charge les routes et filtre selon les types spécifiés
    routes: dict[str, RouteInfo] = {}
    for row in _read_csv_rows(base / "routes.txt"):
        if not _is_kept_route(row, route_types):
            continue
        route_id = row["route_id"]
        routes[route_id] = RouteInfo(
            route_id=route_id,
            route_short_name=row.get("route_short_name", "").strip(),
            route_long_name=(row.get("route_long_name") or "").strip() or None,
            route_type=row.get("route_type", "").strip() or "1",
            route_color=(row.get("route_color") or "").strip() or None,
            route_text_color=(row.get("route_text_color") or "").strip() or None,
        )

    # Charge les voyages (trips) associés aux routes filtrées
    trips: dict[str, TripInfo] = {}
    for row in _read_csv_rows(base / "trips.txt"):
        route_id = row.get("route_id", "").strip()
        if route_id not in routes:
            continue
        trip_id = row["trip_id"]
        service_id = row.get("service_id", "").strip()
        trips[trip_id] = TripInfo(
            trip_id=trip_id,
            route_id=route_id,
            service_id=service_id,
            trip_headsign=(row.get("trip_headsign") or "").strip() or None,
            direction_id=(row.get("direction_id") or "").strip() or None,
            block_id=(row.get("block_id") or "").strip() or None,
            shape_id=(row.get("shape_id") or "").strip() or None,
        )

    # Charge les arrêts associés aux voyages filtrés et construit les connexions du tableau de bord horaire 
    trip_stop_rows: dict[str, list[dict[str, str]]] = {}
    used_stop_ids: set[str] = set()
    for row in _read_csv_rows(base / "stop_times.txt"):
        trip_id = row.get("trip_id", "").strip()
        if trip_id not in trips:
            continue
        trip_stop_rows.setdefault(trip_id, []).append(row)
        stop_id = row.get("stop_id", "").strip()
        if stop_id:
            used_stop_ids.add(stop_id)

    # Charge les arrêts et les groupes de stations associés aux arrêts utilisés dans les voyages filtrés
    raw_stops: dict[str, dict[str, Any]] = {}
    for row in _read_csv_rows(base / "stops.txt"):
        stop_id = row.get("stop_id", "").strip()
        if not stop_id:
            continue
        raw_stops[stop_id] = row

    # Résoud les stations associées aux arrêts utilisés, en construisant des groupes de stations pour les stations parentales et en filtrant les stations sans arrêts utilisés. 
    stop_to_station: dict[str, str] = {}
    station_groups: dict[str, StationGroup] = {}
    stops: dict[str, StopInfo] = {}

    # Retourne la station associée à un arrêt, en utilisant la station parente si elle existe, sinon l'arrêt lui-même.
    def resolve_station_id(stop_id: str) -> str:
        raw = raw_stops.get(stop_id, {})
        parent = (raw.get("parent_station") or "").strip()
        return parent if parent else stop_id

    candidate_station_ids: set[str] = set()
    for stop_id in used_stop_ids:
        candidate_station_ids.add(resolve_station_id(stop_id))

    for stop_id in used_stop_ids:
        row = raw_stops.get(stop_id)
        if not row:
            continue
        station_id = resolve_station_id(stop_id)
        stop_to_station[stop_id] = station_id
        stops[stop_id] = StopInfo(
            stop_id=stop_id,
            name=(row.get("stop_name") or stop_id).strip() or stop_id,
            lat=float(row.get("stop_lat") or 0.0),
            lon=float(row.get("stop_lon") or 0.0),
            parent_station=(row.get("parent_station") or "").strip() or None,
            location_type=(row.get("location_type") or "").strip() or None,
            platform_code=(row.get("platform_code") or "").strip() or None,
            wheelchair_boarding=(row.get("wheelchair_boarding") or "").strip() or None,
        )

    # Construit les groupes de stations pour les stations parentales, en associant les arrêts enfants (platform stops) et en filtrant les stations sans arrêts utilisés.
    skipped_station_ids: list[str] = []
    station_ids_to_create = set(candidate_station_ids)
    for station_id in sorted(station_ids_to_create):
        row = raw_stops.get(station_id)
        platform_stop_ids = [stop_id for stop_id, parent_id in stop_to_station.items() if parent_id == station_id]
        # On garde uniquement les stations qui ont au moins un arrêt utilisé dans les voyages filtrés.
        platform_stop_ids = [sid for sid in platform_stop_ids if sid in stops]
        stop_to_station.setdefault(station_id, station_id)
        if not platform_stop_ids:
            skipped_station_ids.append(station_id)
            continue

        if row:
            station_groups[station_id] = StationGroup(
                station_id=station_id,
                name=(row.get("stop_name") or station_id).strip() or station_id,
                lat=float(row.get("stop_lat") or 0.0),
                lon=float(row.get("stop_lon") or 0.0),
                platform_stop_ids=sorted(platform_stop_ids),
            )
        else:
            # On crée un StationGroup à partir des arrêts enfants si la station parente n'a pas d'entrée valide dans stops.txt.
            name = station_id
            lats: list[float] = []
            lons: list[float] = []
            for sid in platform_stop_ids:
                s = stops.get(sid)
                if not s:
                    continue
                if s.name and name == station_id:
                    name = s.name
                if s.lat:
                    lats.append(s.lat)
                if s.lon:
                    lons.append(s.lon)
            lat = sum(lats) / len(lats) if lats else 0.0
            lon = sum(lons) / len(lons) if lons else 0.0
            station_groups[station_id] = StationGroup(
                station_id=station_id,
                name=name,
                lat=lat,
                lon=lon,
                platform_stop_ids=sorted(platform_stop_ids),
            )

    if skipped_station_ids:
        print(f"Skipped {len(skipped_station_ids)} parent stations with no used platforms; sample: {skipped_station_ids[:10]}")

    # Garde les stations qui n'ont pas d'entrée dans stops.txt mais qui sont référencées par des arrêts utilisés, en créant des StationGroup à partir des arrêts enfants.
    for stop_id, row in raw_stops.items():
        parent = (row.get("parent_station") or "").strip()
        if parent and parent in station_groups:
            stop_to_station[stop_id] = parent
        elif stop_id in used_stop_ids:
            # On crée une station individuelle pour les arrêts utilisés qui ne sont pas associés à une station parente valide, en les traitant comme des stations autonomes.
            stop_to_station.setdefault(stop_id, stop_to_station.get(stop_id, stop_id))

    # Construit les connexions du tableau de bord horaire à partir des voyages filtrés, en reliant les arrêts entre eux pour chaque voyage. 
    connections: list[TimetableConnection] = []
    for trip_id, rows in trip_stop_rows.items():
        trip = trips[trip_id]
        ordered_rows = sorted(rows, key=lambda item: int(item.get("stop_sequence") or 0))
        for index in range(len(ordered_rows) - 1):
            current_row = ordered_rows[index]
            next_row = ordered_rows[index + 1]
            current_dep = current_row.get("departure_time") or current_row.get("arrival_time") or ""
            next_arr = next_row.get("arrival_time") or next_row.get("departure_time") or ""
            if not current_dep or not next_arr:
                continue
            departure_time = time_to_seconds(current_dep)
            arrival_time = time_to_seconds(next_arr)
            if arrival_time <= departure_time:
                continue
            connections.append(
                TimetableConnection(
                    trip_id=trip_id,
                    route_id=trip.route_id,
                    service_id=trip.service_id,
                    from_stop_id=current_row["stop_id"],
                    to_stop_id=next_row["stop_id"],
                    from_stop_sequence=int(current_row.get("stop_sequence") or 0),
                    to_stop_sequence=int(next_row.get("stop_sequence") or 0),
                    departure_time=departure_time,
                    arrival_time=arrival_time,
                    duration=arrival_time - departure_time,
                )
            )

    # Charge les calendriers de service et les exceptions associées aux services référencés par les voyages filtrés.
    services: dict[str, ServiceCalendar] = {}
    calendar_path = base / "calendar.txt"
    if calendar_path.exists():
        for row in _read_csv_rows(calendar_path):
            service_id = row.get("service_id", "").strip()
            if not service_id:
                continue
            services[service_id] = ServiceCalendar(
                service_id=service_id,
                start_date=(row.get("start_date") or "").strip() or None,
                end_date=(row.get("end_date") or "").strip() or None,
                monday=_parse_bool(row.get("monday")),
                tuesday=_parse_bool(row.get("tuesday")),
                wednesday=_parse_bool(row.get("wednesday")),
                thursday=_parse_bool(row.get("thursday")),
                friday=_parse_bool(row.get("friday")),
                saturday=_parse_bool(row.get("saturday")),
                sunday=_parse_bool(row.get("sunday")),
            )

    calendar_dates_path = base / "calendar_dates.txt"
    if calendar_dates_path.exists():
        for row in _read_csv_rows(calendar_dates_path):
            service_id = row.get("service_id", "").strip()
            if not service_id:
                continue
            service = services.setdefault(service_id, ServiceCalendar(service_id=service_id))
            date_value = (row.get("date") or "").strip()
            exception_type = (row.get("exception_type") or "").strip()
            if exception_type == "1":
                service.added_dates.append(date_value)
            elif exception_type == "2":
                service.removed_dates.append(date_value)

    # Charge les transferts définis dans transfers.txt, en filtrant ceux qui ne concernent pas les arrêts utilisés ou les stations associées.
    transfers: list[TransferInfo] = []
    transfers_path = base / "transfers.txt"
    if transfers_path.exists():
        for row in _read_csv_rows(transfers_path):
            from_stop_id = row.get("from_stop_id", "").strip()
            to_stop_id = row.get("to_stop_id", "").strip()
            if not from_stop_id or not to_stop_id:
                continue
            if from_stop_id not in stop_to_station and from_stop_id not in stops:
                continue
            if to_stop_id not in stop_to_station and to_stop_id not in stops:
                continue
            transfers.append(
                TransferInfo(
                    from_stop_id=from_stop_id,
                    to_stop_id=to_stop_id,
                    min_transfer_time=_maybe_int(row.get("min_transfer_time")) or 0,
                    transfer_type=(row.get("transfer_type") or "").strip() or None,
                    from_route_id=(row.get("from_route_id") or "").strip() or None,
                    to_route_id=(row.get("to_route_id") or "").strip() or None,
                )
            )

    connections.sort(key=lambda item: (item.from_stop_id, item.to_stop_id, item.departure_time))

    return PreprocessedGTFS(
        source_dir=str(base),
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        routes=routes,
        services=services,
        stations=station_groups,
        stops=stops,
        trips=trips,
        connections=connections,
        transfers=transfers,
        stop_to_station=stop_to_station,
    )


def save_preprocessed_gtfs(data: PreprocessedGTFS, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_kwargs = dict(ensure_ascii=False, separators=(",", ":"))
    # If output ends with .gz or caller requests .gz by passing a .gz filename, write gzipped text
    if str(path).endswith('.gz'):
        with gzip.open(path, "wt", encoding="utf-8") as file:
            json.dump(data.to_dict(), file, **dump_kwargs)
    else:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data.to_dict(), file, **dump_kwargs)
    return path


def load_preprocessed_gtfs(input_path: str | Path) -> PreprocessedGTFS:
    path = Path(input_path)
    if str(path).endswith('.gz'):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            return PreprocessedGTFS.from_dict(json.load(file))
    with path.open(encoding="utf-8") as file:
        return PreprocessedGTFS.from_dict(json.load(file))


def main() -> None:
    # Ajoute les arguments de ligne de commande.
    parser = argparse.ArgumentParser(description="Preprocess a GTFS feed into a reusable JSON file.")
    parser.add_argument("data_dir", help="Path to the GTFS directory")
    parser.add_argument("output", help="Output JSON file path")
    parser.add_argument(
        "--route-types",
        nargs="*",
        default=sorted(KEPT_ROUTE_TYPES),
        help="GTFS route_type values to keep, for example: 1 2",
    )
    args = parser.parse_args()

    preprocessed = preprocess_gtfs(args.data_dir, route_types=set(args.route_types))
    save_preprocessed_gtfs(preprocessed, args.output)
    print(
        f"Saved {len(preprocessed.stations)} stations, "
        f"{len(preprocessed.trips)} trips and {len(preprocessed.connections)} connections to {args.output}"
    )


if __name__ == "__main__":
    main()