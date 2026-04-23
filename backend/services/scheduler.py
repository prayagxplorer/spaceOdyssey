"""Autonomous maneuver scheduler.

Purpose: Validate, queue, and autonomously generate maneuvers for conjunction avoidance.
Inputs: CDMs, satellite state, LOS checks, and timing/fuel constraints.
Outputs: Ordered maneuver queues, execution logs, and autonomous COLA decisions.
Physical assumptions: Impulsive burns, 600 s cooldown, paired recovery after evasion.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from backend.models.satellite import Maneuver, ObjectState, ObjectType, SatelliteStatus
from backend.physics.maneuver_calc import MAX_BURN_MPS, compute_evasion_burn, compute_recovery_burn, tsiolkovsky_delta_m
from backend.physics.propagator import orbital_period_seconds
from backend.services.los_checker import check_los
from backend.state.sim_state import SimState


def delta_v_magnitude_mps(delta_v_eci_km_s: np.ndarray) -> float:
    return float(np.linalg.norm(delta_v_eci_km_s) * 1000.0)


def validate_sequence(sim_state: SimState, sat: ObjectState, maneuvers: list[Maneuver]) -> tuple[bool, str | None, dict]:
    if sat.type != ObjectType.SATELLITE:
        return False, "Object is not a satellite", {}
    projected_mass = sat.mass_kg
    projected_fuel = sat.fuel_kg
    last_time = sat.last_burn_time or (sim_state.current_time - timedelta(seconds=600))
    los_ok = True
    for maneuver in sorted(maneuvers, key=lambda m: m.burn_time):
        if maneuver.burn_time < sim_state.current_time + timedelta(seconds=10):
            return False, "Burn time violates minimum signal latency", {}
        magnitude = delta_v_magnitude_mps(maneuver.delta_v_eci_km_s)
        if magnitude > MAX_BURN_MPS + 1e-6:
            return False, "Burn exceeds 15.0 m/s limit", {}
        if (maneuver.burn_time - last_time).total_seconds() < 600:
            return False, "Burn sequence violates 600s spacing", {}
        visible, _ = check_los(sim_state, sat.id, maneuver.burn_time)
        los_ok = los_ok and visible
        if not visible:
            return False, "No ground-station LOS at burn time", {}
        fuel_use = tsiolkovsky_delta_m(projected_mass, magnitude)
        projected_fuel -= fuel_use
        projected_mass = sat.dry_mass_kg + projected_fuel
        if projected_fuel < -1e-6:
            return False, "Insufficient fuel for maneuver sequence", {}
        last_time = maneuver.burn_time
    return True, None, {
        "ground_station_los": los_ok,
        "sufficient_fuel": projected_fuel >= 0.0,
        "projected_mass_remaining_kg": round(projected_mass, 3),
    }


def schedule_maneuvers(sim_state: SimState, sat_id: str, maneuvers: list[Maneuver]) -> tuple[bool, str | None, dict]:
    sat = sim_state.get_object(sat_id)
    if sat is None:
        return False, "Satellite does not exist", {}
    ok, reason, validation = validate_sequence(sim_state, sat, maneuvers)
    if not ok:
        return False, reason, {}
    sat.maneuver_queue.extend(maneuvers)
    sat.maneuver_queue.sort(key=lambda m: m.burn_time)
    for maneuver in maneuvers:
        sim_state.log_maneuver(
            {
                "event": "scheduled",
                "satellite_id": sat.id,
                "burn_id": maneuver.burn_id,
                "burn_time": maneuver.burn_time.isoformat(),
                "delta_v_mps": round(delta_v_magnitude_mps(maneuver.delta_v_eci_km_s), 4),
                "fuel_remaining_kg": round(sat.fuel_kg, 4),
                "maneuver_type": maneuver.maneuver_type,
            }
        )
    return True, None, validation


def execute_due_maneuvers(sim_state: SimState, window_start: datetime, window_end: datetime) -> int:
    executed = 0
    cumulative_delta_v = 0.0
    for sat in sim_state.get_satellites():
        due = [m for m in sat.maneuver_queue if window_start <= m.burn_time <= window_end]
        remaining = [m for m in sat.maneuver_queue if m not in due]
        for maneuver in sorted(due, key=lambda m: m.burn_time):
            if sat.cooldown_until and maneuver.burn_time < sat.cooldown_until:
                remaining.append(maneuver)
                continue
            sat.last_burn_time = maneuver.burn_time
            fuel_used = sat.apply_delta_v(maneuver.delta_v_eci_km_s)
            sat.cooldown_until = maneuver.burn_time + timedelta(seconds=600)
            cumulative_delta_v += delta_v_magnitude_mps(maneuver.delta_v_eci_km_s)
            if maneuver.maneuver_type == "EVASION":
                sat.status = SatelliteStatus.EVADING
            sim_state.log_maneuver(
                {
                    "event": "executed",
                    "satellite_id": sat.id,
                    "burn_id": maneuver.burn_id,
                    "burn_time": maneuver.burn_time.isoformat(),
                    "delta_v_mps": round(delta_v_magnitude_mps(maneuver.delta_v_eci_km_s), 4),
                    "fuel_used_kg": round(fuel_used, 6),
                    "new_mass_kg": round(sat.mass_kg, 4),
                    "maneuver_type": maneuver.maneuver_type,
                }
            )
            executed += 1
        sat.maneuver_queue = sorted(remaining, key=lambda m: m.burn_time)
    baseline = sim_state.metrics_history[-1]["cumulative_delta_v_mps"] if sim_state.metrics_history else 0.0
    sim_state.record_metrics(baseline + cumulative_delta_v, len(sim_state.autonomous_conjunctions))
    return executed


def autonomous_cola(sim_state: SimState) -> int:
    scheduled = 0
    now = sim_state.current_time
    for cdm in sim_state.active_cdms:
        if cdm.cdm_id in sim_state.autonomous_conjunctions:
            continue
        sat = sim_state.get_object(cdm.sat_id)
        if sat is None:
            continue
        if any(m.linked_cdm_id == cdm.cdm_id for m in sat.maneuver_queue):
            sim_state.autonomous_conjunctions.add(cdm.cdm_id)
            continue
        evasion = compute_evasion_burn(sat, cdm)
        recovery = compute_recovery_burn(sat)
        period = orbital_period_seconds(sat.r, sat.v)
        proposed_time = max(now + timedelta(seconds=30), cdm.tca - timedelta(seconds=min(1200.0, period * 0.3)))
        visible, station_id = check_los(sim_state, sat.id, proposed_time)
        if not visible:
            candidate = proposed_time - timedelta(seconds=600)
            visible, station_id = check_los(sim_state, sat.id, candidate)
            if visible:
                proposed_time = candidate
        if not visible:
            continue
        recovery_time = max(cdm.tca + timedelta(seconds=300), proposed_time + timedelta(seconds=1200))
        evasion_maneuver = Maneuver(
            burn_id=f"COLA-{sat.id}-{int(proposed_time.timestamp())}",
            burn_time=proposed_time,
            delta_v_eci_km_s=evasion.delta_v_eci_km_s,
            maneuver_type="EVASION",
            linked_cdm_id=cdm.cdm_id,
            metadata={"fuel_cost_kg": evasion.estimated_fuel_kg, "station_id": station_id},
        )
        recovery_maneuver = Maneuver(
            burn_id=f"REC-{sat.id}-{int(recovery_time.timestamp())}",
            burn_time=recovery_time,
            delta_v_eci_km_s=recovery.delta_v_eci_km_s,
            maneuver_type="RECOVERY",
            linked_cdm_id=cdm.cdm_id,
            metadata={"fuel_cost_kg": recovery.estimated_fuel_kg},
        )
        ok, _, _ = schedule_maneuvers(sim_state, sat.id, [evasion_maneuver, recovery_maneuver])
        if ok:
            sat.status = SatelliteStatus.EVADING
            sim_state.autonomous_conjunctions.add(cdm.cdm_id)
            scheduled += 1
    return scheduled
