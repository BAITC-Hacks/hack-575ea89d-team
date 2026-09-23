"""Local incident actions with backend validation and persistent state."""

import json
import sqlite3
from contextlib import closing
from app.config import DB_PATH


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS incident_records (
            id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        )
    """)
    return connection


def get_saved_incidents() -> list[dict]:
    with closing(_connect()) as connection, connection:
        rows = connection.execute("SELECT payload_json FROM incident_records").fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def _save(incident: dict) -> dict:
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO incident_records (id, payload_json) VALUES (?, ?)",
            (incident["id"], json.dumps(incident, ensure_ascii=False)),
        )
    return incident


def _recommended(tower: dict, complaints_count: int) -> tuple[str, str, str]:
    if tower["current_load_pct"] >= 90:
        cause = "network_congestion"
        team = "Network Team A"
        priority = "critical" if tower["current_load_pct"] >= 95 and complaints_count >= 300 else "high"
    elif tower["status"] == "coverage_issue":
        cause = "weak_coverage"
        team = "Radio Planning Team"
        priority = "medium"
    else:
        cause = "network_degradation"
        team = "Network Team A"
        priority = "medium"
    return cause, team, priority


def create_incident(tower_id: int, time_window_minutes: int = 60) -> dict:
    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        from app.services import agent_tools, data_service

        tower = data_service.get_tower(tower_id)
        if tower is None:
            raise ValueError("Unknown tower_id")
        existing = next((item for item in data_service.get_incidents() if item["tower_id"] == tower_id), None)
        if existing is not None:
            return {"incident": existing, "created": False}
        clusters = agent_tools.get_complaints(tower["area"], time_window_minutes)["clusters"]
        complaints_count = next((item["complaints_count"] for item in clusters if item["tower_id"] == tower_id), 0)
        if complaints_count < 10:
            raise ValueError("At least 10 recent complaints are required to create an incident")
        cause, team, priority = _recommended(tower, complaints_count)
        ids = [int(item["id"].split("-")[-1]) for item in data_service.get_incidents()]
        incident = {
            "id": f"INC-{max(ids, default=1041) + 1}",
            "status": "investigating",
            "priority": priority,
            "complaints_count": complaints_count,
            "affected_users": tower["affected_users"],
            "tower_id": tower_id,
            "probable_cause": cause,
            "assigned_team": team,
            "reason": f"Жалобы в зоне Tower #{tower_id} совпадают с состоянием сети.",
            "recurring_days": 0,
        }
        return {"incident": _save_in_connection(connection, incident), "created": True}


def assign_team(incident_id: str, team: str) -> dict:
    from app.services import data_service

    incident = data_service.get_incident(incident_id)
    if incident is None:
        raise ValueError("Unknown incident_id")
    expected = "Radio Planning Team" if incident["probable_cause"] == "weak_coverage" else "Network Team A"
    if team != expected:
        raise ValueError(f"Team must be {expected} for this cause")
    incident = dict(incident, assigned_team=team)
    return {"incident": _save(incident)}


def update_priority(incident_id: str, priority: str) -> dict:
    from app.services import data_service

    incident = data_service.get_incident(incident_id)
    if incident is None:
        raise ValueError("Unknown incident_id")
    tower = data_service.get_tower(incident["tower_id"])
    expected = _recommended(tower, incident["complaints_count"])[2]
    if priority != expected:
        raise ValueError(f"Priority must be {expected} for the current metrics")
    incident = dict(incident, priority=priority)
    return {"incident": _save(incident)}


def _save_in_connection(connection: sqlite3.Connection, incident: dict) -> dict:
    connection.execute("INSERT INTO incident_records (id, payload_json) VALUES (?, ?)",
                       (incident["id"], json.dumps(incident, ensure_ascii=False)))
    return incident
