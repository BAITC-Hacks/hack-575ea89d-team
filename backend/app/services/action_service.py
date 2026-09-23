"""Persist the human-approved infrastructure action in local SQLite."""

import sqlite3
from datetime import datetime, timezone
from contextlib import closing
from app.config import DB_PATH

from app.services import data_service


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS work_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id TEXT NOT NULL,
            tower_id INTEGER NOT NULL,
            solution_type TEXT NOT NULL,
            team TEXT NOT NULL,
            task TEXT NOT NULL,
            budget_kzt INTEGER NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS work_orders_lookup ON work_orders (incident_id, tower_id, solution_type, status)")
    return connection


def _public(row: sqlite3.Row) -> dict:
    return {
        "id": f"WO-{8820 + row['id']}",
        "incident_id": row["incident_id"],
        "tower_id": row["tower_id"],
        "solution_type": row["solution_type"],
        "team": row["team"],
        "task": row["task"],
        "budget_kzt": row["budget_kzt"],
        "priority": row["priority"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def create_work_order(payload: dict) -> dict:
    incident = data_service.get_incident(payload["incident_id"])
    if incident is None:
        raise ValueError("Unknown incident_id")
    if incident["tower_id"] != payload["tower_id"]:
        raise ValueError("Incident and tower do not match")
    solution = next(
        (item for item in data_service.get_solutions() if item["solution_type"] == payload["solution_type"]),
        None,
    )
    if solution is None:
        raise ValueError("Unknown solution_type")
    if solution["cost_kzt"] > payload["budget_kzt"]:
        raise ValueError("Selected solution exceeds budget")

    task = f"{solution['name']} Tower #{payload['tower_id']}"
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection, connection:
        # Serialize the lookup and insert, including requests from other workers.
        # Keep historical duplicates readable; return the oldest pending order.
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM work_orders WHERE incident_id = ? AND tower_id = ? "
            "AND solution_type = ? AND status = 'pending' ORDER BY id LIMIT 1",
            (incident["id"], payload["tower_id"], solution["solution_type"]),
        ).fetchone()
        if existing is not None:
            if existing["budget_kzt"] > payload["budget_kzt"]:
                raise ValueError("Existing pending order exceeds budget")
            return {"work_order": _public(existing), "created": False, "agent_steps": [
                {"tool": "create_work_order", "status": "completed",
                 "message": f"Возвращён ранее созданный заказ WO-{8820 + existing['id']}."}
            ]}
        cursor = connection.execute(
            """INSERT INTO work_orders
            (incident_id, tower_id, solution_type, team, task, budget_kzt, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (incident["id"], payload["tower_id"], solution["solution_type"],
             incident["assigned_team"], task, solution["cost_kzt"], incident["priority"],
             "pending", created_at),
        )
        row = connection.execute("SELECT * FROM work_orders WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"work_order": _public(row), "created": True, "agent_steps": [
        {"tool": "create_work_order", "status": "completed", "message": f"Создан заказ WO-{8820 + row['id']}."}
    ]}


def get_work_order(work_order_id: str) -> dict | None:
    if not work_order_id.startswith("WO-") or not work_order_id[3:].isdigit():
        return None
    row_id = int(work_order_id[3:]) - 8820
    if row_id < 1:
        return None
    with closing(_connect()) as connection, connection:
        row = connection.execute("SELECT * FROM work_orders WHERE id = ?", (row_id,)).fetchone()
    return _public(row) if row else None


def list_work_orders(incident_id: str | None = None, limit: int = 100) -> list[dict]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM work_orders WHERE (? IS NULL OR incident_id = ?) ORDER BY id DESC LIMIT ?",
            (incident_id, incident_id, limit),
        ).fetchall()
    return [_public(row) for row in rows]
