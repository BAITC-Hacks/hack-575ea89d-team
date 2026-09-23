from typing import Literal

from pydantic import BaseModel, Field


SolutionType = Literal["upgrade_existing", "additional_equipment", "new_tower"]


class AnalyzeRequest(BaseModel):
    incident_id: str | None = Field(default=None, min_length=1, max_length=100)
    area: str | None = Field(default=None, max_length=200)
    time_window_minutes: int = Field(default=60, ge=1, le=10080)
    complaint_text: str | None = Field(default=None, max_length=4000)


class SimulateRequest(BaseModel):
    tower_id: int
    budget_kzt: int = Field(ge=0)


class ActionRequest(BaseModel):
    incident_id: str
    tower_id: int
    solution_type: SolutionType
    budget_kzt: int = Field(ge=0)
