"""ACM FastAPI entrypoint.

Purpose: Initialize simulation state, mount APIs and frontend assets, and serve the ACM.
Inputs: Ground station CSV, synthetic constellation/debris generation, API requests.
Outputs: HTTP services, seeded in-memory simulation, and static frontend delivery.
Physical assumptions: Circular-orbit synthetic seed generation with J2-aware propagation.
"""

from __future__ import annotations

import csv
import asyncio
import json
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.maneuver import router as maneuver_router
from backend.api.simulate import router as simulate_router
from backend.api.telemetry import router as telemetry_router
from backend.api.visualization import router as visualization_router
from backend.models.cdm import CDM
from backend.models.satellite import INITIAL_FUEL_KG, Maneuver, ObjectState, ObjectType, SatelliteStatus
from backend.physics.maneuver_calc import compute_evasion_burn, compute_recovery_burn
from backend.physics.conjunction import run_conjunction_assessment
from backend.physics.propagator import MU_EARTH, orbital_period_seconds
from backend.state.sim_state import GroundStation, sim_state


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": datetime.now(timezone.utc).isoformat(),
        }
        return json.dumps(payload)


logger = logging.getLogger("acm")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


async def background_initial_cdm_sweep() -> None:
    cdms = await run_conjunction_assessment(
        sim_state,
        time_window_seconds=6 * 3600,
        sample_step_seconds=60,
        max_candidates=250,
    )
    for cdm in cdms[:20]:
        logger.info(
            "CDM generated sat=%s deb=%s tca=%s miss_km=%.6f",
            cdm.sat_id,
            cdm.deb_id,
            cdm.tca.isoformat(),
            cdm.miss_distance_km,
        )


def rotation_matrix_raan_inclination_true_anomaly(raan: float, inclination: float, true_anomaly: float) -> np.ndarray:
    cos_o, sin_o = np.cos(raan), np.sin(raan)
    cos_i, sin_i = np.cos(inclination), np.sin(inclination)
    cos_f, sin_f = np.cos(true_anomaly), np.sin(true_anomaly)
    return np.array(
        [
            [cos_o * cos_f - sin_o * sin_f * cos_i, -cos_o * sin_f - sin_o * cos_f * cos_i, sin_o * sin_i],
            [sin_o * cos_f + cos_o * sin_f * cos_i, -sin_o * sin_f + cos_o * cos_f * cos_i, -cos_o * sin_i],
            [sin_f * sin_i, cos_f * sin_i, cos_i],
        ]
    )


def circular_orbit_state(altitude_km: float, inclination_deg: float, raan_deg: float, true_anomaly_deg: float) -> tuple[np.ndarray, np.ndarray]:
    radius = 6378.137 + altitude_km
    speed = np.sqrt(MU_EARTH / radius)
    rotation = rotation_matrix_raan_inclination_true_anomaly(
        np.deg2rad(raan_deg), np.deg2rad(inclination_deg), np.deg2rad(true_anomaly_deg)
    )
    perifocal_r = np.array([radius, 0.0, 0.0], dtype=float)
    perifocal_v = np.array([0.0, speed, 0.0], dtype=float)
    return rotation @ perifocal_r, rotation @ perifocal_v


def load_ground_stations() -> None:
    sim_state.ground_stations.clear()
    candidates = [
        Path("/app/data/ground_stations.csv"),
        Path(__file__).resolve().parent / "data" / "ground_stations.csv",
    ]
    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    sim_state.ground_stations.append(
                        GroundStation(
                            station_id=row["station_id"],
                            name=row["name"],
                            latitude_deg=float(row["latitude_deg"]),
                            longitude_deg=float(row["longitude_deg"]),
                            altitude_m=float(row["altitude_m"]),
                            min_elevation_deg=float(row["min_elevation_deg"]),
                        )
                    )
            logger.info("Loaded %s ground stations from %s", len(sim_state.ground_stations), path)
            return
    raise FileNotFoundError("ground_stations.csv not found in /app/data or backend/data")


def seed_objects() -> None:
    rng = random.Random(2026)
    sim_state.state_store.clear()
    sim_state.active_cdms.clear()
    sim_state.demo_cdms.clear()
    sim_state.autonomous_conjunctions.clear()
    sim_state.maneuver_log.clear()
    sim_state.collision_log.clear()
    sim_state.metrics_history.clear()
    for index in range(50):
        altitude = 500.0 + (index % 10) * 10.0
        inclination = 45.0 + (index % 11) * (53.0 / 10.0)
        raan = (360.0 / 50.0) * index
        anomaly = (360.0 / 50.0) * ((index * 7) % 50)
        r, v = circular_orbit_state(altitude, inclination, raan, anomaly)
        sat = ObjectState(
            id=f"SAT-Alpha-{index + 1:02d}",
            type=ObjectType.SATELLITE,
            r=r,
            v=v,
            mass_kg=500.0 + INITIAL_FUEL_KG,
            fuel_kg=INITIAL_FUEL_KG,
            status=SatelliteStatus.NOMINAL,
            nominal_slot_r=r.copy(),
            nominal_slot_v=v.copy(),
            cooldown_until=None,
            last_updated=sim_state.current_time,
        )
        sim_state.upsert_object(sat)
    for index in range(1500):
        altitude = max(250.0, rng.gauss(550.0, 80.0))
        inclination = rng.uniform(0.0, 98.0)
        raan = rng.uniform(0.0, 360.0)
        anomaly = rng.uniform(0.0, 360.0)
        r, v = circular_orbit_state(altitude, inclination, raan, anomaly)
        v = v + np.array([rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1)], dtype=float)
        deb = ObjectState(
            id=f"DEB-{index + 1:05d}",
            type=ObjectType.DEBRIS,
            r=r,
            v=v,
            mass_kg=5.0,
            fuel_kg=0.0,
            status=SatelliteStatus.NOMINAL,
            nominal_slot_r=r.copy(),
            nominal_slot_v=v.copy(),
            cooldown_until=None,
            last_updated=sim_state.current_time,
        )
        sim_state.upsert_object(deb)
    sim_state.rebuild_spatial_index()
    sim_state.record_metrics(0.0, 0)


def seed_demo_scenarios() -> None:
    demo_sat_ids = ["SAT-Alpha-03", "SAT-Alpha-11", "SAT-Alpha-27"]
    offsets = [
        np.array([0.08, -0.03, 0.01], dtype=float),
        np.array([-0.06, 0.04, -0.02], dtype=float),
        np.array([0.05, 0.05, 0.0], dtype=float),
    ]
    for index, sat_id in enumerate(demo_sat_ids):
        sat = sim_state.get_object(sat_id)
        if sat is None:
            continue
        tca = sim_state.current_time + timezone_agnostic_seconds(900 + index * 360)
        debris = ObjectState(
            id=f"DEB-DEMO-{index + 1:02d}",
            type=ObjectType.DEBRIS,
            r=sat.r + offsets[index],
            v=sat.v + np.array([0.0, -0.00008 * (index + 1), 0.00003 * index], dtype=float),
            mass_kg=8.0,
            fuel_kg=0.0,
            status=SatelliteStatus.NOMINAL,
            nominal_slot_r=(sat.r + offsets[index]).copy(),
            nominal_slot_v=sat.v.copy(),
            cooldown_until=None,
            last_updated=sim_state.current_time,
        )
        sim_state.upsert_object(debris)
        cdm = CDM(
            sat_id=sat.id,
            deb_id=debris.id,
            tca=tca,
            miss_distance_km=0.04 + index * 0.015,
            Pc=0.18 - index * 0.05,
            approach_vector=offsets[index] * 18.0,
            created_at=sim_state.current_time,
            coarse_distance_km=float(np.linalg.norm(offsets[index])),
        )
        sim_state.demo_cdms.append(cdm)
        sat.active_cdms.append(cdm.cdm_id)
        evasion = compute_evasion_burn(sat, cdm)
        recovery = compute_recovery_burn(sat)
        evasion_time = sim_state.current_time + timezone_agnostic_seconds(120 + index * 60)
        recovery_time = sim_state.current_time + timezone_agnostic_seconds(1800 + index * 240)
        sat.maneuver_queue.extend(
            [
                Maneuver(
                    burn_id=f"DEMO-COLA-{sat.id}",
                    burn_time=evasion_time,
                    delta_v_eci_km_s=evasion.delta_v_eci_km_s,
                    maneuver_type="EVASION",
                    linked_cdm_id=cdm.cdm_id,
                    metadata={"fuel_cost_kg": evasion.estimated_fuel_kg, "demo": True},
                ),
                Maneuver(
                    burn_id=f"DEMO-REC-{sat.id}",
                    burn_time=recovery_time,
                    delta_v_eci_km_s=recovery.delta_v_eci_km_s,
                    maneuver_type="RECOVERY",
                    linked_cdm_id=cdm.cdm_id,
                    metadata={"fuel_cost_kg": recovery.estimated_fuel_kg, "demo": True},
                ),
            ]
        )
        sat.maneuver_queue.sort(key=lambda maneuver: maneuver.burn_time)
        sat.status = SatelliteStatus.EVADING if index == 0 else SatelliteStatus.RECOVERING
        sim_state.log_maneuver(
            {
                "event": "scheduled",
                "satellite_id": sat.id,
                "burn_id": f"DEMO-COLA-{sat.id}",
                "burn_time": evasion_time.isoformat(),
                "delta_v_mps": round(evasion.magnitude_mps, 4),
                "fuel_remaining_kg": round(sat.fuel_kg, 4),
                "maneuver_type": "EVASION",
            }
        )
    sim_state.rebuild_spatial_index()


def timezone_agnostic_seconds(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sim_state.current_time = datetime.now(timezone.utc)
    load_ground_stations()
    seed_objects()
    seed_demo_scenarios()
    asyncio.create_task(background_initial_cdm_sweep())
    yield


app = FastAPI(title="Autonomous Constellation Manager", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry_router)
app.include_router(maneuver_router)
app.include_router(simulate_router)
app.include_router(visualization_router)


@app.get("/api/logs/maneuvers")
async def get_maneuver_logs() -> dict:
    return {"timestamp": sim_state.current_time.isoformat(), "entries": list(sim_state.maneuver_log)[-500:]}


@app.get("/api/status/fleet")
async def get_fleet_status() -> dict:
    summary = sim_state.snapshot_mass_budget()
    summary["satellites"] = [
        {
            "id": sat.id,
            "fuel_kg": round(sat.fuel_kg, 4),
            "mass_kg": round(sat.mass_kg, 4),
            "status": sat.status.value,
            "period_s": round(orbital_period_seconds(sat.r, sat.v), 2),
        }
        for sat in sim_state.get_satellites()
    ]
    return summary


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "timestamp": sim_state.current_time.isoformat()})


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
