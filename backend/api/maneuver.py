"""Maneuver scheduling API.

Purpose: Validate and queue external maneuver requests for tracked satellites.
Inputs: Satellite ID and a time-ordered sequence of impulsive delta-v commands.
Outputs: 202 response on success or 400 validation error on constraint failure.
Physical assumptions: Commands are executed instantaneously at scheduled burn time.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from backend.models.satellite import Maneuver
from backend.services.scheduler import schedule_maneuvers
from backend.state.sim_state import sim_state

router = APIRouter(tags=["maneuver"])


class Vector3(BaseModel):
    x: float
    y: float
    z: float


class BurnCommand(BaseModel):
    burn_id: str
    burnTime: datetime
    deltaV_vector: Vector3


class ManeuverScheduleRequest(BaseModel):
    satelliteId: str
    maneuver_sequence: list[BurnCommand] = Field(default_factory=list)


@router.post("/api/maneuver/schedule")
async def schedule_maneuver(payload: ManeuverScheduleRequest, response: Response) -> dict:
    maneuvers = [
        Maneuver(
            burn_id=burn.burn_id,
            burn_time=burn.burnTime,
            delta_v_eci_km_s=np.array([burn.deltaV_vector.x, burn.deltaV_vector.y, burn.deltaV_vector.z], dtype=float)
            / 1000.0,
            maneuver_type="MANUAL",
        )
        for burn in payload.maneuver_sequence
    ]
    ok, reason, validation = schedule_maneuvers(sim_state, payload.satelliteId, maneuvers)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "SCHEDULED", "validation": validation}
