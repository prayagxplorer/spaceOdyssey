"""Station-keeping monitor.

Purpose: Track drift from nominal orbital slots and request recovery maneuvers.
Inputs: Current and nominal satellite state vectors after each propagation chunk.
Outputs: Updated recovery status, counter-based completion, and queued burns.
Physical assumptions: 10 km spherical station-keeping box and tangential phasing recovery.
"""

from __future__ import annotations

from datetime import timedelta

from backend.models.satellite import Maneuver, ObjectState, SatelliteStatus
from backend.physics.maneuver_calc import compute_station_recovery_burn
from backend.physics.propagator import norm
from backend.state.sim_state import SimState


def evaluate_station_keeping(sim_state: SimState, sat: ObjectState) -> bool:
    drift_distance = norm(sat.r - sat.nominal_slot_r)
    if drift_distance > 10.0:
        sat.status = SatelliteStatus.RECOVERING
        sat.recovery_checks = 0
        has_recovery = any(m.maneuver_type == "RECOVERY" for m in sat.maneuver_queue)
        if not has_recovery:
            recovery = compute_station_recovery_burn(sat)
            sat.maneuver_queue.append(
                Maneuver(
                    burn_id=f"REC-{sat.id}-{int(sim_state.current_time.timestamp())}",
                    burn_time=sim_state.current_time + timedelta(seconds=120),
                    delta_v_eci_km_s=recovery.delta_v_eci_km_s,
                    maneuver_type="RECOVERY",
                    metadata={"fuel_cost_kg": recovery.estimated_fuel_kg, "drift_distance_km": drift_distance},
                )
            )
        return False
    sat.recovery_checks += 1
    if sat.recovery_checks >= 3 and sat.status == SatelliteStatus.RECOVERING:
        sat.status = SatelliteStatus.NOMINAL
    return True
