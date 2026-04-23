"""Orbit propagation and coordinate transforms.

Purpose: Numerically propagate ECI states with optional J2 perturbation and convert
between ECI, ECEF, and geodetic views for the API and dashboard.
Inputs: State vectors, target times, and Earth constants.
Outputs: Propagated position/velocity states plus frame-conversion helpers.
Physical assumptions: Two-body gravity with J2, spherical Earth geodetic conversion.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, atan2, cos, floor, pi, sin, sqrt
from typing import Iterable

import numpy as np

from backend.models.satellite import ObjectState

MU_EARTH = 398600.4418
J2 = 1.08263e-3
EARTH_RADIUS_KM = 6378.137
_EXECUTOR = ThreadPoolExecutor(max_workers=8)


@dataclass(slots=True)
class PropagationResult:
    r: np.ndarray
    v: np.ndarray


def norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def acceleration_eci(r_km: np.ndarray, include_j2: bool = True) -> np.ndarray:
    radius = norm(r_km)
    base = -MU_EARTH / radius**3 * r_km
    if not include_j2:
        return base
    x, y, z = r_km
    factor = 1.5 * J2 * MU_EARTH * EARTH_RADIUS_KM**2 / radius**5
    z2_r2 = 5.0 * z * z / radius**2
    a_j2 = factor * np.array(
        [
            x * (z2_r2 - 1.0),
            y * (z2_r2 - 1.0),
            z * (z2_r2 - 3.0),
        ],
        dtype=float,
    )
    return base + a_j2


def rk4_step(r_km: np.ndarray, v_km_s: np.ndarray, dt_s: float, include_j2: bool = True) -> tuple[np.ndarray, np.ndarray]:
    def deriv(state: np.ndarray) -> np.ndarray:
        r = state[:3]
        v = state[3:]
        a = acceleration_eci(r, include_j2)
        return np.concatenate([v, a])

    state = np.concatenate([r_km, v_km_s])
    k1 = deriv(state)
    k2 = deriv(state + 0.5 * dt_s * k1)
    k3 = deriv(state + 0.5 * dt_s * k2)
    k4 = deriv(state + dt_s * k3)
    next_state = state + (dt_s / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
    return next_state[:3], next_state[3:]


def adaptive_rk4_propagate(
    r_km: np.ndarray,
    v_km_s: np.ndarray,
    dt_s: float,
    include_j2: bool = True,
    min_step_s: float = 1.0,
    max_step_s: float = 60.0,
    tolerance_km: float = 1e-3,
) -> PropagationResult:
    remaining = float(dt_s)
    current_r = r_km.copy()
    current_v = v_km_s.copy()
    step_size = min(max_step_s, max(min_step_s, abs(remaining)))
    direction = 1.0 if remaining >= 0 else -1.0
    while abs(remaining) > 1e-9:
        step = min(step_size, abs(remaining)) * direction
        r_full, v_full = rk4_step(current_r, current_v, step, include_j2=include_j2)
        r_half, v_half = rk4_step(current_r, current_v, step / 2.0, include_j2=include_j2)
        r_half, v_half = rk4_step(r_half, v_half, step / 2.0, include_j2=include_j2)
        error = norm(r_half - r_full)
        if error > tolerance_km and abs(step) > min_step_s:
            step_size = max(min_step_s, abs(step) / 2.0)
            continue
        current_r, current_v = r_half, v_half
        remaining -= step
        if error < tolerance_km / 8.0:
            step_size = min(max_step_s, abs(step) * 2.0)
        else:
            step_size = abs(step)
    return PropagationResult(current_r, current_v)


def propagate_object(
    obj: ObjectState,
    dt_s: float,
    include_j2: bool = True,
    cache_callback: callable | None = None,
    start_time: datetime | None = None,
) -> PropagationResult:
    r = obj.r.copy()
    v = obj.v.copy()
    remaining = float(dt_s)
    current_time = start_time
    direction = 1.0 if remaining >= 0 else -1.0
    while abs(remaining) > 1e-9:
        chunk = min(60.0, abs(remaining)) * direction
        result = adaptive_rk4_propagate(r, v, chunk, include_j2=include_j2)
        r, v = result.r, result.v
        if current_time is not None:
            current_time = current_time + timedelta(seconds=chunk)
            if cache_callback is not None:
                cache_callback(current_time, obj.id, r, v)
        remaining -= chunk
    return PropagationResult(r, v)


async def propagate_all_parallel(
    objects: Iterable[ObjectState],
    dt_s: float,
    include_j2: bool = True,
    cache_callback: callable | None = None,
    start_time: datetime | None = None,
) -> dict[str, PropagationResult]:
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(_EXECUTOR, propagate_object, obj, dt_s, include_j2, cache_callback, start_time)
        for obj in objects
    ]
    results = await asyncio.gather(*tasks)
    return {obj.id: result for obj, result in zip(objects, results)}


def julian_date(moment: datetime) -> float:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    year = moment.year
    month = moment.month
    day = moment.day + (
        moment.hour + (moment.minute + (moment.second + moment.microsecond / 1e6) / 60.0) / 60.0
    ) / 24.0
    if month <= 2:
        year -= 1
        month += 12
    a = floor(year / 100)
    b = 2 - a + floor(a / 4)
    return floor(365.25 * (year + 4716)) + floor(30.6001 * (month + 1)) + day + b - 1524.5


def gast_angle(moment: datetime) -> float:
    jd = julian_date(moment)
    t_ut1 = (jd - 2451545.0) / 36525.0
    gmst_deg = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t_ut1**2
        - t_ut1**3 / 38710000.0
    )
    return np.deg2rad(gmst_deg % 360.0)


def eci_to_ecef(r_eci_km: np.ndarray, moment: datetime) -> np.ndarray:
    theta = gast_angle(moment)
    rotation = np.array(
        [
            [cos(theta), sin(theta), 0.0],
            [-sin(theta), cos(theta), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=float,
    )
    return rotation @ r_eci_km


def geodetic_to_ecef(lat_deg: float, lon_deg: float, altitude_m: float = 0.0) -> np.ndarray:
    lat = np.deg2rad(lat_deg)
    lon = np.deg2rad(lon_deg)
    radius = EARTH_RADIUS_KM + altitude_m / 1000.0
    return np.array(
        [
            radius * cos(lat) * cos(lon),
            radius * cos(lat) * sin(lon),
            radius * sin(lat),
        ],
        dtype=float,
    )


def ecef_to_geodetic(r_ecef_km: np.ndarray) -> tuple[float, float, float]:
    radius = norm(r_ecef_km)
    lat = asin(r_ecef_km[2] / radius)
    lon = atan2(r_ecef_km[1], r_ecef_km[0])
    alt = radius - EARTH_RADIUS_KM
    return float(np.rad2deg(lat)), float(np.rad2deg(lon)), float(alt)


def eci_to_geodetic(r_eci_km: np.ndarray, moment: datetime) -> tuple[float, float, float]:
    return ecef_to_geodetic(eci_to_ecef(r_eci_km, moment))


def orbital_period_seconds(r_km: np.ndarray, v_km_s: np.ndarray) -> float:
    r = norm(r_km)
    v = norm(v_km_s)
    specific_energy = v**2 / 2.0 - MU_EARTH / r
    semi_major_axis = -MU_EARTH / (2.0 * specific_energy)
    return float(2.0 * pi * sqrt(semi_major_axis**3 / MU_EARTH))
