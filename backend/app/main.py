from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import ActionRequest, AnalyzeRequest, SimulateRequest
from app.services import action_service, analysis_service, data_service, simulation_service

app = FastAPI(title="Network Intelligence Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/towers")
def towers() -> dict:
    return {"items": data_service.get_towers(), "data_source": "synthetic"}


@app.get("/incidents")
def incidents() -> dict:
    return {"items": data_service.get_incidents(), "data_source": "synthetic"}


@app.get("/incidents/{incident_id}")
def incident(incident_id: str) -> dict:
    item = data_service.get_incident(incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown incident_id")
    return {"incident": item, "data_source": "synthetic"}


@app.post("/analyze")
def analyze(payload: AnalyzeRequest) -> dict:
    return analysis_service.analyze(payload.model_dump())


@app.post("/simulate")
def simulate(payload: SimulateRequest) -> dict:
    try:
        return simulation_service.simulate(payload.tower_id, payload.budget_kzt)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/action")
def action(payload: ActionRequest) -> dict:
    try:
        return action_service.create_work_order(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
