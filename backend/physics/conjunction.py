"""Conjunction assessment engine.

Purpose: Detect satellite-debris close approaches using KD-tree coarse filtering and
forward propagation to estimate time of closest approach and collision probability.
Inputs: Shared simulation state containing satellites, debris, and spatial index.
Outputs: Sorted CDM records for downstream autonomous scheduling and visualization.
Physical assumptions: Piecewise-propagated relative motion and simplified Chan Pc.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from math import exp

import numpy as np

from backend.models.cdm import CDM
from backend.models.satellite import ObjectState, ObjectType
from backend.physics.propagator import adaptive_rk4_propagate, norm
from backend.state.sim_state import SimState

COARSE_RADIUS_KM = 50.0
TCA_WINDOW_SECONDS = 24 * 3600
SAMPLE_STEP_SECONDS = 10
CDM_THRESHOLD_KM = 0.1


def chan_collision_probability(miss_distance_km: float, sigma_km: float = 0.05, hard_body_radius_km: float = 0.02) -> float:
    if miss_distance_km <= 0:
        return 1.0
    exponent = -0.5 * (miss_distance_km / max(sigma_km, 1e-6)) ** 2
    area_ratio = min(1.0, (hard_body_radius_km / max(miss_distance_km, hard_body_radius_km)) ** 2)
    return float(min(1.0, area_ratio * exp(exponent)))


def propagate_pair_distance(sat: ObjectState, deb: ObjectState, dt_s: float) -> tuple[float, np.ndarray]:
    sat_state = adaptive_rk4_propagate(sat.r, sat.v, dt_s, include_j2=True)
    deb_state = adaptive_rk4_propagate(deb.r, deb.v, dt_s, include_j2=True)
    rel = deb_state.r - sat_state.r
    return norm(rel), rel


def ternary_search_tca(sat: ObjectState, deb: ObjectState, lo_s: float, hi_s: float) -> tuple[float, float, np.ndarray]:
    left = lo_s
    right = hi_s
    best_distance = float("inf")
    best_time = left
    best_vector = np.zeros(3, dtype=float)
    for _ in range(20):
        m1 = left + (right - left) / 3.0
        m2 = right - (right - left) / 3.0
        d1, v1 = propagate_pair_distance(sat, deb, m1)
        d2, v2 = propagate_pair_distance(sat, deb, m2)
        if d1 < best_distance:
            best_distance, best_time, best_vector = d1, m1, v1
        if d2 < best_distance:
            best_distance, best_time, best_vector = d2, m2, v2
        if d1 < d2:
            right = m2
        else:
            left = m1
    return best_time, best_distance, best_vector


def evaluate_candidate_pair(
    sat: ObjectState,
    deb: ObjectState,
    created_at,
    time_window_seconds: int = TCA_WINDOW_SECONDS,
    sample_step_seconds: int = SAMPLE_STEP_SECONDS,
) -> CDM | None:
    best_distance = float("inf")
    best_step = 0.0
    best_vector = np.zeros(3, dtype=float)
    for step in range(0, time_window_seconds + sample_step_seconds, sample_step_seconds):
        distance, rel = propagate_pair_distance(sat, deb, float(step))
        if distance < best_distance:
            best_distance = distance
            best_step = float(step)
            best_vector = rel
    search_lo = max(0.0, best_step - sample_step_seconds)
    search_hi = min(float(time_window_seconds), best_step + sample_step_seconds)
    tca_seconds, miss_distance, approach_vector = ternary_search_tca(sat, deb, search_lo, search_hi)
    if miss_distance >= CDM_THRESHOLD_KM:
        return None
    pc = chan_collision_probability(miss_distance)
    return CDM(
        sat_id=sat.id,
        deb_id=deb.id,
        tca=created_at + timedelta(seconds=tca_seconds),
        miss_distance_km=miss_distance,
        Pc=pc,
        approach_vector=approach_vector,
        created_at=created_at,
        coarse_distance_km=best_distance,
    )


async def run_conjunction_assessment(
    sim_state: SimState,
    *,
    coarse_radius_km: float = COARSE_RADIUS_KM,
    time_window_seconds: int = TCA_WINDOW_SECONDS,
    sample_step_seconds: int = SAMPLE_STEP_SECONDS,
    max_candidates: int | None = None,
) -> list[CDM]:
    satellites = sim_state.get_satellites()
    if sim_state.kd_tree is None or not satellites:
        sim_state.active_cdms = []
        return []
    id_to_object = {obj.id: obj for obj in sim_state.state_store.values()}
    coarse_pairs: set[tuple[str, str]] = set()
    for sat in satellites:
        idx = sim_state.kd_tree.query_ball_point(sat.r, r=coarse_radius_km)
        for candidate_idx in idx:
            candidate_id = sim_state.kd_tree_ids[candidate_idx]
            if candidate_id == sat.id:
                continue
            obj = id_to_object[candidate_id]
            if obj.type == ObjectType.DEBRIS:
                coarse_pairs.add((sat.id, obj.id))
    ordered_pairs = sorted(
        coarse_pairs,
        key=lambda pair: norm(id_to_object[pair[0]].r - id_to_object[pair[1]].r),
    )
    if max_candidates is not None:
        ordered_pairs = ordered_pairs[:max_candidates]
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            None,
            evaluate_candidate_pair,
            id_to_object[sat_id],
            id_to_object[deb_id],
            sim_state.current_time,
            time_window_seconds,
            sample_step_seconds,
        )
        for sat_id, deb_id in ordered_pairs
    ]
    results = [cdm for cdm in await asyncio.gather(*tasks) if cdm is not None]
    results.sort(key=lambda c: c.tca)
    sim_state.active_cdms = results
    active_by_sat: dict[str, list[str]] = {}
    for cdm in results:
        active_by_sat.setdefault(cdm.sat_id, []).append(cdm.cdm_id)
    for sat in satellites:
        sat.active_cdms = active_by_sat.get(sat.id, [])
    return results
