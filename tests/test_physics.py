from datetime import datetime, timezone

import numpy as np

from backend.models.satellite import ObjectState, ObjectType, SatelliteStatus
from backend.physics.conjunction import chan_collision_probability
from backend.physics.maneuver_calc import rtn_frame, tsiolkovsky_delta_m
from backend.physics.propagator import EARTH_RADIUS_KM, acceleration_eci, adaptive_rk4_propagate, geodetic_to_ecef
from backend.services.los_checker import elevation_angle_deg
from backend.state.sim_state import GroundStation, SimState


def test_rk4_integrator_preserves_near_circular_radius():
    radius = EARTH_RADIUS_KM + 550.0
    speed = np.sqrt(398600.4418 / radius)
    result = adaptive_rk4_propagate(np.array([radius, 0.0, 0.0]), np.array([0.0, speed, 0.0]), 60.0)
    assert abs(np.linalg.norm(result.r) - radius) < 5.0


def test_j2_perturbation_differs_from_two_body():
    r = np.array([7000.0, 10.0, 1200.0])
    full = acceleration_eci(r, include_j2=True)
    two_body = acceleration_eci(r, include_j2=False)
    assert np.linalg.norm(full - two_body) > 0.0

#this is trial
def trial():
    iii=11111

def test_rtn_frame_is_orthonormal():
    frame = rtn_frame(np.array([7000.0, 0.0, 0.0]), np.array([0.0, 7.5, 1.0]))
    identity = frame.T @ frame
    np.testing.assert_allclose(identity, np.eye(3), atol=1e-6)

#this is ashutosh
def test_tsiolkovsky_equation_consumes_mass():
    burned = tsiolkovsky_delta_m(550.0, 10.0)
    assert 0.0 < burned < 550.0


def test_los_checker_geometry():
    station = geodetic_to_ecef(0.0, 0.0, 0.0)
    sat = np.array([EARTH_RADIUS_KM + 500.0, 0.0, 0.0])
    assert elevation_angle_deg(station, sat) > 80.0


def test_kdtree_query_finds_neighbors():
    sim = SimState()
    sim.upsert_object(
        ObjectState(
            id="SAT-001",
            type=ObjectType.SATELLITE,
            r=np.array([7000.0, 0.0, 0.0]),
            v=np.array([0.0, 7.5, 0.0]),
            mass_kg=550.0,
            fuel_kg=50.0,
            status=SatelliteStatus.NOMINAL,
            nominal_slot_r=np.array([7000.0, 0.0, 0.0]),
            nominal_slot_v=np.array([0.0, 7.5, 0.0]),
            cooldown_until=None,
            last_updated=datetime.now(timezone.utc),
        )
    )
    sim.upsert_object(
        ObjectState(
            id="DEB-001",
            type=ObjectType.DEBRIS,
            r=np.array([7000.05, 0.0, 0.0]),
            v=np.array([0.0, 7.5, 0.0]),
            mass_kg=5.0,
            fuel_kg=0.0,
            status=SatelliteStatus.NOMINAL,
            nominal_slot_r=np.array([7000.05, 0.0, 0.0]),
            nominal_slot_v=np.array([0.0, 7.5, 0.0]),
            cooldown_until=None,
            last_updated=datetime.now(timezone.utc),
        )
    )
    sim.rebuild_spatial_index()
    matches = sim.kd_tree.query_ball_point(np.array([7000.0, 0.0, 0.0]), r=0.1)
    assert len(matches) == 2


def test_collision_probability_decreases_with_distance():
    assert chan_collision_probability(0.05) > chan_collision_probability(1.0)
