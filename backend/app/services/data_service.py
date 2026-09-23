"""Read-only access and small calculations over the synthetic demo dataset."""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def read_json(name: str):
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def get_towers() -> list[dict]:
    return read_json("towers.json")


def get_tower(tower_id: int) -> dict | None:
    return next((item for item in get_towers() if item["id"] == tower_id), None)


def find_nearest_tower(lat: float, lon: float) -> dict | None:
    """Return the nearest tower by haversine distance, including distance_km."""
    closest = None
    for tower in get_towers():
        lat1, lat2 = math.radians(lat), math.radians(tower["lat"])
        dlat = lat2 - lat1
        dlon = math.radians(tower["lon"] - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        if closest is None or distance < closest["distance_km"]:
            closest = {**tower, "distance_km": round(distance, 3)}
    return closest


def get_population(area: str | None = None) -> list[dict] | dict | None:
    rows = read_json("population.json")
    if area is None:
        return rows
    return next((row for row in rows if row["area"] == area), None)


def get_complaints(area: str | None = None, tower_id: int | None = None) -> list[dict]:
    rows = read_json("complaints.json")
    if tower_id is not None:
        rows = [row for row in rows if row.get("tower_id") == tower_id]
    if area is not None:
        rows = [row for row in rows if row.get("area") == area]
    return rows


def get_incidents() -> list[dict]:
    from app.services import incident_service

    combined = {item["id"]: item for item in read_json("incidents.json")}
    combined.update({item["id"]: item for item in incident_service.get_saved_incidents()})
    return list(combined.values())


def get_incident(incident_id: str) -> dict | None:
    return next((item for item in get_incidents() if item["id"] == incident_id), None)


def get_solutions() -> list[dict]:
    return read_json("solutions.json")
