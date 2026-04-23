"""End-of-life manager.

Purpose: Trigger graveyard-orbit handling when satellites cross the fuel reserve limit.
Inputs: Satellite state immediately after maneuver execution or health checks.
Outputs: Updated status, queued EOL maneuver, and logged lifecycle events.
Physical assumptions: Graveyard action is modeled as a single tangential apogee-raise burn.
"""

from __future__ import annotations

from datetime import timedelta

from backend.models.satellite import Maneuver, ObjectState, SatelliteStatus
from backend.physics.maneuver_calc import hohmann_like_raise_apogee
from backend.state.sim_state import SimState


def maybe_trigger_eol(sim_state: SimState, sat: ObjectState) -> bool:
    fuel_ratio = sat.fuel_kg / max(sat.fuel_kg + sat.dry_mass_kg, 1.0)
    if fuel_ratio >= 0.05 or sat.status == SatelliteStatus.EOL:
        return False
    sat.status = SatelliteStatus.EOL
    burn = hohmann_like_raise_apogee(sat, 200.0)
    maneuver = Maneuver(
        burn_id=f"EOL-{sat.id}-{int(sim_state.current_time.timestamp())}",
        burn_time=sim_state.current_time + timedelta(seconds=20),
        delta_v_eci_km_s=burn.delta_v_eci_km_s,
        maneuver_type="EOL",
        metadata={"fuel_cost_kg": burn.estimated_fuel_kg, "priority": "HIGH"},
    )
    sat.maneuver_queue.insert(0, maneuver)
    sim_state.log_event(
        "WARNING",
        "eol_trigger",
        {
            "satellite_id": sat.id,
            "timestamp": sim_state.current_time.isoformat(),
            "remaining_fuel_kg": round(sat.fuel_kg, 4),
            "burn_id": maneuver.burn_id,
        },
    )
    return True
