from app.services import data_service


def analyze(_request: dict) -> dict:
    # Working demo fallback. Participant 1 will replace this with tool calling.
    incident = data_service.get_incident("INC-1042")
    return {
        "incident": incident,
        "recurring": incident["recurring_days"] >= 7,
        "solution_options": data_service.get_solutions(),
        "agent_steps": [
            {"status": "completed", "message": "Загружены синтетические жалобы и сетевые показатели."},
            {"status": "completed", "message": "Найден демонстрационный инцидент около Tower #17."},
            {"status": "completed", "message": "Проверена история инцидента и получены варианты решения."},
        ],
        "data_source": "synthetic",
    }
