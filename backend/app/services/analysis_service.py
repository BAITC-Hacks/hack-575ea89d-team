"""Agent orchestration with a truthful local demo path."""

import json
import os
from pathlib import Path
from time import monotonic

from dotenv import load_dotenv

from app.services import agent_tools, data_service

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

INSTRUCTIONS = """You are a mobile network operations analyst for a synthetic hackathon demo.
Call get_complaints, get_incidents, and get_network_data before deciding. If recent complaints
form a new cluster without an incident, call create_incident. Confirm team and priority with
assign_team and update_priority. If an incident recurs, call calculate_solution. Use only IDs
and facts returned by tools. Do not invent
counts, costs, loads, users, or completed actions. Return only JSON with incident_id
(an existing ID from get_incidents) and reason (one concise Russian sentence without
numeric claims). If no suitable incident exists, return {"incident_id": null, "reason": ""}.
Do not create a work order during analysis; a human selects a solution separately."""

# Frontend waits 45 seconds. Reserve time for the local fallback and HTTP response.
MODEL_DEADLINE_SECONDS = 35
MODEL_REQUEST_TIMEOUT_SECONDS = 8


def _step_message(name: str, result: dict) -> str:
    if "error" in result:
        return result["error"]
    if name == "get_complaints":
        return f"Проверены жалобы: {result['total']} записей в выбранном окне."
    if name == "get_towers":
        return f"Получены данные о {len(result['items'])} вышках."
    if name == "get_incidents":
        return f"Получены данные о {len(result['items'])} инцидентах."
    if name == "get_network_data":
        return f"Проверена Tower #{result['tower']['id']} и история её инцидентов."
    if name == "calculate_solution":
        return f"Рассчитаны {len(result['options'])} варианта решения."
    if name == "create_incident":
        return f"Инцидент {result['incident']['id']} {'создан' if result['created'] else 'уже существует'}."
    if name == "assign_team":
        return f"Инцидент {result['incident']['id']} назначен команде {result['incident']['assigned_team']}."
    if name == "update_priority":
        return f"Приоритет инцидента {result['incident']['id']} подтверждён: {result['incident']['priority']}."
    raise ValueError(f"Unknown agent tool: {name}")


def _execute(name: str, arguments: dict, steps: list[dict]) -> dict:
    if name not in agent_tools.TOOLS:
        raise ValueError(f"Unknown agent tool: {name}")
    try:
        result = agent_tools.TOOLS[name](**arguments)
    except (TypeError, ValueError) as exc:
        result = {"error": str(exc)}
        status = "error"
    else:
        status = "completed"
    steps.append({"tool": name, "arguments": arguments, "status": status, "message": _step_message(name, result)})
    return result


def _candidates(area: str | None) -> list[dict]:
    return agent_tools.get_incidents(area)["items"]


def _demo_path(request: dict, steps: list[dict]) -> tuple[str | None, str | None]:
    area = request.get("area")
    summary = _execute("get_complaints", {"area": area, "time_window_minutes": request["time_window_minutes"]}, steps)
    incidents = _execute("get_incidents", {"area": area}, steps)["items"]
    by_tower = {item["tower_id"]: item["complaints_count"] for item in summary["clusters"]}
    if by_tower:
        busiest_tower = max(by_tower, key=by_tower.get)
        if by_tower[busiest_tower] >= 10 and not any(item["tower_id"] == busiest_tower for item in incidents):
            created = _execute("create_incident", {"tower_id": busiest_tower,
                                                   "time_window_minutes": request["time_window_minutes"]}, steps)
            if "error" not in created:
                incidents.append(created["incident"])
    if not incidents:
        return None, None
    if by_tower:
        incident = max(incidents, key=lambda item: (by_tower.get(item["tower_id"], 0), item["complaints_count"]))
    else:
        incident = max(incidents, key=lambda item: item["complaints_count"])
    _execute("get_network_data", {"tower_id": incident["tower_id"]}, steps)
    _execute("update_priority", {"incident_id": incident["id"], "priority": incident["priority"]}, steps)
    _execute("assign_team", {"incident_id": incident["id"], "team": incident["assigned_team"]}, steps)
    if incident.get("recurring_days", 0) >= 7:
        _execute("calculate_solution", {"tower_id": incident["tower_id"]}, steps)
    return incident["id"], None


def _model_path(request: dict, steps: list[dict]) -> tuple[str | None, str | None]:
    from openai import OpenAI

    client = OpenAI(timeout=MODEL_REQUEST_TIMEOUT_SECONDS, max_retries=0)
    input_items = [{"role": "user", "content": f"Analyze this request using tools: {json.dumps(request, ensure_ascii=False)}"}]
    called = set()
    checked_towers = set()
    simulated_towers = set()
    deadline = monotonic() + MODEL_DEADLINE_SECONDS
    for _ in range(12):
        remaining = deadline - monotonic()
        if remaining < 1:
            raise TimeoutError("OpenAI analysis exceeded its time budget")
        response = client.responses.create(
            model=os.environ["OPENAI_MODEL"], instructions=INSTRUCTIONS,
            input=input_items, tools=agent_tools.TOOL_SCHEMAS,
            timeout=min(MODEL_REQUEST_TIMEOUT_SECONDS, remaining),
        )
        input_items.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            if not {"get_complaints", "get_incidents", "get_network_data"}.issubset(called):
                raise ValueError("Model stopped before checking required evidence")
            try:
                decision = json.loads(response.output_text)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("Model did not return valid decision JSON") from exc
            incident_id = decision.get("incident_id")
            selected = data_service.get_incident(incident_id) if incident_id else None
            if selected is not None:
                tower_id = selected["tower_id"]
                if tower_id not in checked_towers:
                    raise ValueError("Model did not check the selected tower")
                if selected.get("recurring_days", 0) >= 7 and tower_id not in simulated_towers:
                    raise ValueError("Model did not calculate recurring-issue options")
            return incident_id, decision.get("reason")
        for call in calls:
            try:
                arguments = json.loads(call.arguments)
                result = _execute(call.name, arguments, steps)
                if "error" not in result:
                    called.add(call.name)
                    if call.name == "get_network_data":
                        checked_towers.add(arguments["tower_id"])
                    elif call.name == "calculate_solution":
                        simulated_towers.add(arguments["tower_id"])
            except (TypeError, json.JSONDecodeError, ValueError) as exc:
                result = {"error": str(exc)}
                steps.append({"tool": call.name, "status": "error", "message": str(exc)})
            input_items.append({
                "type": "function_call_output", "call_id": call.call_id,
                "output": json.dumps(result, ensure_ascii=False),
            })
    raise ValueError("Model exceeded tool-call limit")


def analyze(request: dict) -> dict:
    steps: list[dict] = []
    mode = "openai" if os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL") else "demo"
    if mode == "openai":
        try:
            incident_id, explanation = _model_path(request, steps)
        except Exception as exc:
            steps.append({"status": "error", "message": f"OpenAI analysis unavailable: {type(exc).__name__}"})
            mode = "demo_fallback"
            incident_id, explanation = _demo_path(request, steps)
    else:
        incident_id, explanation = _demo_path(request, steps)

    allowed = {item["id"]: item for item in _candidates(request.get("area"))}
    incident = allowed.get(incident_id)
    if incident is None:
        return {"incident": None, "recurring": False, "solution_options": [],
                "agent_steps": steps, "agent_mode": mode, "data_source": "synthetic"}

    incident = dict(incident)
    # Canonical numbers/cause/team come from Python data, never model output.
    if isinstance(explanation, str) and 0 < len(explanation) <= 300 and not any(ch.isdigit() for ch in explanation):
        incident["reason"] = explanation
    recurring = incident.get("recurring_days", 0) >= 7
    solutions = data_service.get_solutions() if recurring else []
    return {"incident": incident, "recurring": recurring, "solution_options": solutions,
            "agent_steps": steps, "agent_mode": mode, "data_source": "synthetic"}
