"""Ground-station visibility service.

Purpose: Validate whether a satellite has line-of-sight to at least one ground station.
Inputs: Satellite ID, candidate execution time, loaded ground station catalog.
Outputs: LOS boolean and the visible station identifier when available.
Physical assumptions: Spherical Earth, geometric elevation-angle visibility threshold.
"""

from __future__ import annotations

from datetime import datetime
from math import asin, degrees

import numpy as np

from backend.physics.propagator import eci_to_ecef, geodetic_to_ecef, norm
from backend.state.sim_state import SimState


def elevation_angle_deg(station_ecef_km: np.ndarray, sat_ecef_km: np.ndarray) -> float:
    los = sat_ecef_km - station_ecef_km
    los_hat = los / norm(los)
    zenith_hat = station_ecef_km / norm(station_ecef_km)
    return float(degrees(asin(np.clip(np.dot(los_hat, zenith_hat), -1.0, 1.0))))


def check_los(sim_state: SimState, sat_id: str, time: datetime) -> tuple[bool, str | None]:
    sat = sim_state.get_object(sat_id)
    if sat is None:
        return False, None
    sat_ecef = eci_to_ecef(sat.r, time)
    for station in sim_state.ground_stations:
        station_ecef = geodetic_to_ecef(station.latitude_deg, station.longitude_deg, station.altitude_m)
        if elevation_angle_deg(station_ecef, sat_ecef) >= station.min_elevation_deg:
            return True, station.station_id
    return False, None
