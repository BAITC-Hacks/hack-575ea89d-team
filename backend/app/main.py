from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import CORS_ORIGINS
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import ActionRequest, AnalyzeRequest, SimulateRequest
from app.services import action_service, analysis_service, data_service, simulation_service

app = FastAPI(title="Network Intelligence Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
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
    try:
        return analysis_service.analyze(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@app.get("/work-orders/{work_order_id}")
def work_order(work_order_id: str) -> dict:
    item = action_service.get_work_order(work_order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown work_order_id")
    return {"work_order": item}


@app.get("/work-orders")
def work_orders(incident_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return {"items": action_service.list_work_orders(incident_id, limit)}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/app.js", include_in_schema=False)
def dashboard_script():
    return FileResponse(FRONTEND_DIR / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/styles.css", include_in_schema=False)
def dashboard_styles():
    return FileResponse(FRONTEND_DIR / "styles.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/appearance.js", include_in_schema=False)
def dashboard_appearance():
    return FileResponse(FRONTEND_DIR / "appearance.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
