from itertools import count

from app.services import data_service

_work_order_ids = count(8821)


def create_work_order(payload: dict) -> dict:
    incident = data_service.get_incident(payload["incident_id"])
    if incident is None:
        raise ValueError("Unknown incident_id")
    if incident["tower_id"] != payload["tower_id"]:
        raise ValueError("Incident and tower do not match")
    solution = next((item for item in data_service.get_solutions() if item["solution_type"] == payload["solution_type"]), None)
    if solution is None:
        raise ValueError("Unknown solution_type")
    if solution["cost_kzt"] > payload["budget_kzt"]:
        raise ValueError("Selected solution exceeds budget")
    return {"work_order": {
        "id": f"WO-{next(_work_order_ids)}",
        "team": incident["assigned_team"],
        "task": f"{solution['name']} Tower #{payload['tower_id']}",
        "budget_kzt": solution["cost_kzt"],
        "priority": incident["priority"],
        "status": "pending",
    }}
