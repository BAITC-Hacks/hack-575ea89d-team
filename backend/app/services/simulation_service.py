from app.services import data_service


def simulate(tower_id: int, budget_kzt: int) -> dict:
    tower = data_service.get_tower(tower_id)
    if tower is None:
        raise ValueError(f"Unknown tower_id: {tower_id}")
    options = []
    for solution in data_service.get_solutions():
        capacity_gain = solution["capacity_increase_pct"]
        options.append({
            **solution,
            "available": solution["cost_kzt"] <= budget_kzt,
            # Synthetic capacity-only model; assumptions in docs/DEMO_MODEL.md.
            "expected_load_pct": round(tower["current_load_pct"] / (1 + capacity_gain / 100)),
            "affected_users_improved": round(tower["affected_users"] * min(capacity_gain / 70, 1)),
        })
    return {"tower_id": tower_id, "budget_kzt": budget_kzt, "options": options, "data_source": "synthetic_simulation"}
