"""Telemetry ingest API.

Purpose: Accept real-time object updates and trigger conjunction re-evaluation.
Inputs: Batch telemetry payloads with ECI position and velocity vectors.
Outputs: ACK response with processed object count and active CDM count.
Physical assumptions: Latest telemetry fully replaces tracked kinematic state.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.models.satellite import INITIAL_FUEL_KG, ObjectState, ObjectType, SatelliteStatus
from backend.physics.conjunction import run_conjunction_assessment
from backend.state.sim_state import sim_state

router = APIRouter(tags=["telemetry"])


class Vector3(BaseModel):
    x: float
    y: float
    z: float


class TelemetryObject(BaseModel):
    id: str
    type: ObjectType
    r: Vector3
    v: Vector3


class TelemetryRequest(BaseModel):
    timestamp: datetime
    objects: list[TelemetryObject] = Field(default_factory=list)


@router.post("/api/telemetry")
async def post_telemetry(payload: TelemetryRequest) -> dict[str, int | str]:
    processed_count = 0
    for item in payload.objects:
        r = np.array([item.r.x, item.r.y, item.r.z], dtype=float)
        v = np.array([item.v.x, item.v.y, item.v.z], dtype=float)
        existing = sim_state.get_object(item.id)
        if existing is None:
            state = ObjectState(
                id=item.id,
                type=item.type,
                r=r,
                v=v,
                mass_kg=550.0 if item.type == ObjectType.SATELLITE else 5.0,
                fuel_kg=INITIAL_FUEL_KG if item.type == ObjectType.SATELLITE else 0.0,
                status=SatelliteStatus.NOMINAL,
                nominal_slot_r=r.copy(),
                nominal_slot_v=v.copy(),
                cooldown_until=None,
                last_updated=payload.timestamp,
            )
            sim_state.upsert_object(state)
        else:
            existing.r = r
            existing.v = v
            existing.last_updated = payload.timestamp
        processed_count += 1
    sim_state.current_time = payload.timestamp
    sim_state.rebuild_spatial_index()
    cdms = await run_conjunction_assessment(sim_state)
    sim_state.log_event(
        "INFO",
        "telemetry_batch",
        {
            "count": processed_count,
            "timestamp": payload.timestamp.isoformat(),
            "active_cdm_warnings": len(cdms),
        },
    )
    return {"status": "ACK", "processed_count": processed_count, "active_cdm_warnings": len(cdms)}
