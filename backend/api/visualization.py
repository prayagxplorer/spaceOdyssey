"""Visualization snapshot API.

Purpose: Deliver compact real-time constellation data to the Orbital Insight dashboard.
Inputs: Current simulation state, geodetic conversion helpers, and active CDM list.
Outputs: Flattened satellite, debris, and conjunction view models optimized for polling.
Physical assumptions: ECI-to-geodetic conversion uses Greenwich sidereal rotation.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.physics.propagator import eci_to_geodetic
from backend.state.sim_state import sim_state

router = APIRouter(tags=["visualization"])


@router.get("/api/visualization/snapshot")
async def visualization_snapshot() -> dict:
    timestamp = sim_state.current_time
    satellites = []
    debris_cloud = []
    all_cdms = sorted(sim_state.demo_cdms + sim_state.active_cdms, key=lambda cdm: cdm.tca)
    cdm_by_sat: dict[str, list[str]] = {}
    for cdm in all_cdms:
        cdm_by_sat.setdefault(cdm.sat_id, []).append(cdm.cdm_id)
    for sat in sim_state.get_satellites():
        lat, lon, alt = eci_to_geodetic(sat.r, timestamp)
        satellites.append(
            {
                "id": sat.id,
                "lat": lat,
                "lon": lon,
                "alt_km": alt,
                "fuel_kg": round(sat.fuel_kg, 4),
                "status": sat.status.value,
                "active_cdms": len(cdm_by_sat.get(sat.id, [])),
                "active_cdm_ids": cdm_by_sat.get(sat.id, []),
                "is_demo": sat.id in {cdm.sat_id for cdm in sim_state.demo_cdms},
                "maneuver_queue": [
                    {
                        "burn_id": m.burn_id,
                        "burnTime": m.burn_time.isoformat(),
                        "delta_v_mps": round(m.delta_v_mps(), 4),
                        "maneuver_type": m.maneuver_type,
                        "fuel_cost_kg": round(float(m.metadata.get("fuel_cost_kg", 0.0)), 6),
                    }
                    for m in sat.maneuver_queue
                ],
            }
        )
    for deb in sim_state.get_debris():
        lat, lon, alt = eci_to_geodetic(deb.r, timestamp)
        debris_cloud.append([deb.id, lat, lon, alt])
    active_conjunctions = [
        {
            "sat_id": cdm.sat_id,
            "deb_id": cdm.deb_id,
            "tca_seconds": max(0.0, (cdm.tca - timestamp).total_seconds()),
            "miss_distance_km": cdm.miss_distance_km,
            "risk": cdm.risk,
            "approach_vector": [float(value) for value in cdm.approach_vector.tolist()],
            "is_demo": cdm in sim_state.demo_cdms,
        }
        for cdm in all_cdms
    ]
    return {
        "timestamp": timestamp.isoformat(),
        "satellites": satellites,
        "debris_cloud": debris_cloud,
        "active_conjunctions": active_conjunctions,
        "metrics": list(sim_state.metrics_history)[-120:],
        "recent_maneuvers": list(sim_state.maneuver_log)[-20:],
        "recent_collisions": list(sim_state.collision_log)[-10:],
        "event_log": [
            {
                "level": event.level,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
            }
            for event in list(sim_state.event_log)[-20:]
        ],
    }
