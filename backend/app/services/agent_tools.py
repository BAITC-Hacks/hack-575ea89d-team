"""Bounded, JSON-safe tools available to the network agent."""

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services import data_service, incident_service, simulation_service


def _parse_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def get_complaints(area: str | None = None, time_window_minutes: int = 60) -> dict:
    """Summarize complaints by tower; do not send thousands of raw texts to the model."""
    rows = data_service.read_json("complaints.json")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=time_window_minutes)
    matches = [
        row for row in rows
        if (area is None or row.get("area") == area)
        and (timestamp := _parse_time(row.get("timestamp") or row.get("time"))) is not None
        and cutoff <= timestamp <= now
    ]
    by_tower = Counter(row.get("tower_id") for row in matches if row.get("tower_id") is not None)
    clusters = []
    for tower_id, count in by_tower.most_common():
        tower_rows = [row for row in matches if row.get("tower_id") == tower_id]
        issue_types = Counter(row.get("issue_type", "unknown") for row in tower_rows)
        samples = [row["text"][:180] for row in tower_rows if isinstance(row.get("text"), str)][:3]
        clusters.append({"tower_id": tower_id, "complaints_count": count,
                         "issue_types": dict(issue_types), "sample_texts": samples})
    return {"total": len(matches), "clusters": clusters, "source": "complaints_json"}


def get_towers(area: str | None = None) -> dict:
    rows = data_service.get_towers()
    return {"items": [row for row in rows if area is None or row.get("area") == area]}


def get_incidents(area: str | None = None) -> dict:
    towers = {tower["id"]: tower for tower in data_service.get_towers()}
    rows = data_service.get_incidents()
    items = [row for row in rows if area is None or towers.get(row["tower_id"], {}).get("area") == area]
    return {"items": items, "source": "synthetic_incident_records"}


def get_network_data(tower_id: int) -> dict:
    tower = data_service.get_tower(tower_id)
    if tower is None:
        raise ValueError(f"Unknown tower_id: {tower_id}")
    history = [item for item in data_service.get_incidents() if item["tower_id"] == tower_id]
    recommendations = {}
    for item in history:
        _, team, priority = incident_service._recommended(tower, item["complaints_count"])
        recommendations[item["id"]] = {"team": team, "priority": priority}
    return {"tower": tower, "incidents": history, "recommendations": recommendations,
            "source": "synthetic_network_data"}


def calculate_solution(tower_id: int) -> dict:
    # Python simulation owns prices and estimated effects.
    return simulation_service.simulate(tower_id, 10**12)


TOOLS = {
    "get_complaints": get_complaints,
    "get_towers": get_towers,
    "get_incidents": get_incidents,
    "get_network_data": get_network_data,
    "calculate_solution": calculate_solution,
    "create_incident": incident_service.create_incident,
    "assign_team": incident_service.assign_team,
    "update_priority": incident_service.update_priority,
}


TOOL_SCHEMAS = [
    {
        "type": "function", "name": "get_complaints",
        "description": "Count recent synthetic complaints and group them by tower. Call before choosing an incident.",
        "parameters": {"type": "object", "properties": {
            "area": {"type": ["string", "null"]},
            "time_window_minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
        }, "required": ["area", "time_window_minutes"], "additionalProperties": False},
        "strict": True,
    },
    {
        "type": "function", "name": "get_towers",
        "description": "Read synthetic tower locations and network indicators.",
        "parameters": {"type": "object", "properties": {"area": {"type": ["string", "null"]}},
                       "required": ["area"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "get_incidents",
        "description": "Read existing incident fixtures and their history; select an incident ID from these results.",
        "parameters": {"type": "object", "properties": {"area": {"type": ["string", "null"]}},
                       "required": ["area"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "get_network_data",
        "description": "Read load, status, affected users and history for a known tower.",
        "parameters": {"type": "object", "properties": {"tower_id": {"type": "integer"}},
                       "required": ["tower_id"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "calculate_solution",
        "description": "Calculate exact synthetic infrastructure options and effects for a tower.",
        "parameters": {"type": "object", "properties": {"tower_id": {"type": "integer"}},
                       "required": ["tower_id"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "create_incident",
        "description": "Create an incident only for a tower with at least 10 recent complaints; existing tower incidents are returned unchanged.",
        "parameters": {"type": "object", "properties": {
            "tower_id": {"type": "integer"},
            "time_window_minutes": {"type": "integer", "minimum": 1, "maximum": 10080},
        }, "required": ["tower_id", "time_window_minutes"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "assign_team",
        "description": "Confirm the responsible team for an existing incident; Python validates it against the cause.",
        "parameters": {"type": "object", "properties": {
            "incident_id": {"type": "string"}, "team": {"type": "string"},
        }, "required": ["incident_id", "team"], "additionalProperties": False}, "strict": True,
    },
    {
        "type": "function", "name": "update_priority",
        "description": "Confirm incident priority; Python validates it against load and complaint count.",
        "parameters": {"type": "object", "properties": {
            "incident_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["critical", "high", "medium"]},
        }, "required": ["incident_id", "priority"], "additionalProperties": False}, "strict": True,
    },
]
