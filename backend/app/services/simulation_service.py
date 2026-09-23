from app.services import data_service


def simulate(tower_id: int, budget_kzt: int) -> dict:
    tower = data_service.get_tower(tower_id)
    if tower is None:
        raise ValueError(f"Unknown tower_id: {tower_id}")
    options = []
    for solution in data_service.get_solutions():
        capacity_factor = 1 + solution["capacity_increase_pct"] / 100
        expected_load = tower["current_load_pct"] / capacity_factor
        load_reduction_fraction = max(0, tower["current_load_pct"] - expected_load) / 100
        coverage_user_fraction = solution["coverage_increase_pct"] / 100
        # Approximation: users helped by capacity relief or expanded coverage are
        # estimated from the tower's affected_users count, capped at that count.
        improved_fraction = min(1, load_reduction_fraction + coverage_user_fraction)
        options.append({
            **solution,
            "available": solution["cost_kzt"] <= budget_kzt,
            "expected_load_pct": round(expected_load),
            "affected_users_improved": round(tower["affected_users"] * improved_fraction),
        })
    return {"tower_id": tower_id, "budget_kzt": budget_kzt, "options": options, "data_source": "synthetic_simulation"}
