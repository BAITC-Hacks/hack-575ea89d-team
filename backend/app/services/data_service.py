import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def read_json(name: str):
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def get_towers() -> list[dict]:
    return read_json("towers.json")


def get_tower(tower_id: int) -> dict | None:
    return next((item for item in get_towers() if item["id"] == tower_id), None)


def get_incidents() -> list[dict]:
    from app.services import incident_service

    combined = {item["id"]: item for item in read_json("incidents.json")}
    combined.update({item["id"]: item for item in incident_service.get_saved_incidents()})
    return list(combined.values())


def get_incident(incident_id: str) -> dict | None:
    return next((item for item in get_incidents() if item["id"] == incident_id), None)


def get_solutions() -> list[dict]:
    return read_json("solutions.json")
