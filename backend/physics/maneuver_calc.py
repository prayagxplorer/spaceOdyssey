"""Maneuver design and fuel accounting.

Purpose: Compute RTN-frame burns for collision avoidance and station recovery.
Inputs: Satellite states, conjunction geometry, target slot states, and mission limits.
Outputs: ECI delta-v vectors, fuel usage estimates, and phasing burns.
Physical assumptions: Impulsive burns, small-angle phasing, T-axis preference.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, sqrt

import numpy as np

from backend.models.cdm import CDM
from backend.models.satellite import DEFAULT_ISP_S, G0_MPS2, ObjectState
from backend.physics.propagator import MU_EARTH, norm, orbital_period_seconds

MAX_BURN_MPS = 15.0
STANDOFF_KM = 0.2


@dataclass(slots=True)
class BurnSolution:
    delta_v_eci_km_s: np.ndarray
    delta_v_rtn_km_s: np.ndarray
    magnitude_mps: float
    estimated_fuel_kg: float


def rtn_frame(r_km: np.ndarray, v_km_s: np.ndarray) -> np.ndarray:
    r_hat = r_km / norm(r_km)
    w_hat = np.cross(r_km, v_km_s)
    w_hat = w_hat / norm(w_hat)
    t_hat = np.cross(w_hat, r_hat)
    return np.column_stack([r_hat, t_hat, w_hat])


def rtn_to_eci(delta_v_rtn_km_s: np.ndarray, r_km: np.ndarray, v_km_s: np.ndarray) -> np.ndarray:
    return rtn_frame(r_km, v_km_s) @ delta_v_rtn_km_s


def tsiolkovsky_delta_m(m_current_kg: float, delta_v_mps: float, isp_s: float = DEFAULT_ISP_S) -> float:
    return m_current_kg * (1.0 - exp(-abs(delta_v_mps) / (isp_s * G0_MPS2)))


def clamp_delta_v(delta_v_mps: float) -> float:
    return float(np.clip(delta_v_mps, -MAX_BURN_MPS, MAX_BURN_MPS))


def sqrt_mu_over_r(radius_km: float) -> float:
    return float(sqrt(MU_EARTH / radius_km))


def compute_evasion_burn(sat: ObjectState, cdm: CDM) -> BurnSolution:
    period = orbital_period_seconds(sat.r, sat.v)
    tca_seconds = max((cdm.tca - cdm.created_at).total_seconds(), 1.0)
    desired_shift_km = max(STANDOFF_KM - cdm.miss_distance_km, 0.0) + STANDOFF_KM
    if tca_seconds > 2.0 * period:
        delta_v_mps = clamp_delta_v(-desired_shift_km / tca_seconds * 1000.0 * 0.5)
    else:
        delta_v_mps = clamp_delta_v(desired_shift_km / tca_seconds * 1000.0 * 1.2)
    delta_v_rtn = np.array([0.0, delta_v_mps / 1000.0, 0.0], dtype=float)
    delta_v_eci = rtn_to_eci(delta_v_rtn, sat.r, sat.v)
    fuel = tsiolkovsky_delta_m(sat.mass_kg, abs(delta_v_mps))
    return BurnSolution(delta_v_eci, delta_v_rtn, abs(delta_v_mps), fuel)


def compute_recovery_burn(sat: ObjectState) -> BurnSolution:
    actual_radius = norm(sat.r)
    nominal_radius = norm(sat.nominal_slot_r)
    delta_radius = nominal_radius - actual_radius
    circular_speed = sqrt_mu_over_r(actual_radius)
    delta_v_mps = clamp_delta_v((delta_radius / max(actual_radius, 1.0)) * circular_speed * 1000.0 * 0.5)
    delta_v_rtn = np.array([0.0, delta_v_mps / 1000.0, 0.0], dtype=float)
    delta_v_eci = rtn_to_eci(delta_v_rtn, sat.r, sat.v)
    fuel = tsiolkovsky_delta_m(sat.mass_kg, abs(delta_v_mps))
    return BurnSolution(delta_v_eci, delta_v_rtn, abs(delta_v_mps), fuel)


def compute_station_recovery_burn(sat: ObjectState) -> BurnSolution:
    drift = sat.nominal_slot_r - sat.r
    frame = rtn_frame(sat.r, sat.v)
    drift_rtn = frame.T @ drift
    tangential_bias_mps = clamp_delta_v(drift_rtn[1] * 0.06)
    radial_trim_mps = clamp_delta_v(drift_rtn[0] * 0.03)
    delta_v_rtn = np.array([radial_trim_mps / 1000.0, tangential_bias_mps / 1000.0, 0.0], dtype=float)
    delta_v_eci = frame @ delta_v_rtn
    magnitude_mps = float(np.linalg.norm(delta_v_rtn) * 1000.0)
    fuel = tsiolkovsky_delta_m(sat.mass_kg, magnitude_mps)
    return BurnSolution(delta_v_eci, delta_v_rtn, magnitude_mps, fuel)


def hohmann_like_raise_apogee(sat: ObjectState, raise_km: float = 200.0) -> BurnSolution:
    radius = norm(sat.r)
    target_radius = radius + raise_km
    dv1 = sqrt_mu_over_r(radius) * (sqrt(2.0 * target_radius / (radius + target_radius)) - 1.0)
    delta_v_mps = clamp_delta_v(dv1 * 1000.0)
    delta_v_rtn = np.array([0.0, delta_v_mps / 1000.0, 0.0], dtype=float)
    delta_v_eci = rtn_to_eci(delta_v_rtn, sat.r, sat.v)
    fuel = tsiolkovsky_delta_m(sat.mass_kg, abs(delta_v_mps))
    return BurnSolution(delta_v_eci, delta_v_rtn, abs(delta_v_mps), fuel)
