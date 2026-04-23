"""Simulation-step API.

Purpose: Advance the constellation state, execute due burns, and evaluate safety logic.
Inputs: Requested simulation step duration in seconds.
Outputs: Completion response with new time, collision count, and executed maneuvers.
Physical assumptions: Propagation in substeps <= 60 s, impulsive maneuvers, point collisions.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.models.satellite import SatelliteStatus
from backend.physics.conjunction import run_conjunction_assessment
from backend.physics.propagator import propagate_all_parallel
from backend.services.eol_manager import maybe_trigger_eol
from backend.services.scheduler import autonomous_cola, execute_due_maneuvers
from backend.services.station_keeping import evaluate_station_keeping
from backend.state.sim_state import sim_state

router = APIRouter(tags=["simulate"])
FAST_CA_WINDOW_SECONDS = 2 * 3600
FAST_CA_STEP_SECONDS = 60
FAST_CA_MAX_CANDIDATES = 120


class SimulationStepRequest(BaseModel):
    step_seconds: int


@router.post("/api/simulate/step")
async def simulate_step(payload: SimulationStepRequest) -> dict[str, int | str]:
    if payload.step_seconds <= 0:
        raise HTTPException(status_code=400, detail="step_seconds must be positive")
    start_time = sim_state.current_time
    end_time = sim_state.current_time + timedelta(seconds=payload.step_seconds)
    maneuvers_executed = 0
    collisions_detected = 0
    remaining = payload.step_seconds
    while remaining > 0:
        chunk = min(60, remaining)
        chunk_start = sim_state.current_time
        chunk_end = sim_state.current_time + timedelta(seconds=chunk)
        maneuvers_executed += execute_due_maneuvers(sim_state, chunk_start, chunk_end)
        objects = list(sim_state.state_store.values())
        results = await propagate_all_parallel(
            objects,
            float(chunk),
            include_j2=True,
            cache_callback=sim_state.cache_state,
            start_time=sim_state.current_time,
        )
        nominal_results = await propagate_all_parallel(sim_state.get_satellites(), float(chunk), include_j2=False)
        for obj in objects:
            result = results[obj.id]
            obj.r = result.r
            obj.v = result.v
            obj.last_updated = chunk_end
            if obj.id in nominal_results:
                obj.nominal_slot_r = nominal_results[obj.id].r
                obj.nominal_slot_v = nominal_results[obj.id].v
        sim_state.current_time = chunk_end
        sim_state.rebuild_spatial_index()
        cdms = await run_conjunction_assessment(
            sim_state,
            time_window_seconds=FAST_CA_WINDOW_SECONDS,
            sample_step_seconds=FAST_CA_STEP_SECONDS,
            max_candidates=FAST_CA_MAX_CANDIDATES,
        )
        autonomous_cola(sim_state)
        for sat in sim_state.get_satellites():
            evaluate_station_keeping(sim_state, sat)
            maybe_trigger_eol(sim_state, sat)
        for cdm in cdms:
            if cdm.miss_distance_km < 0.1:
                sat = sim_state.get_object(cdm.sat_id)
                deb = sim_state.get_object(cdm.deb_id)
                if sat and deb:
                    sat.collision_count += 1
                    sat.status = SatelliteStatus.COLLIDED
                    sim_state.log_collision(
                        {
                            "satellite_id": sat.id,
                            "debris_id": deb.id,
                            "timestamp": sim_state.current_time.isoformat(),
                            "miss_distance_km": cdm.miss_distance_km,
                        }
                    )
                    collisions_detected += 1
        remaining -= chunk
    sim_state.log_event(
        "INFO",
        "step_complete",
        {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "collisions_detected": collisions_detected,
            "maneuvers_executed": maneuvers_executed,
        },
    )
    return {
        "status": "STEP_COMPLETE",
        "new_timestamp": sim_state.current_time.isoformat(),
        "collisions_detected": collisions_detected,
        "maneuvers_executed": maneuvers_executed,
    }
