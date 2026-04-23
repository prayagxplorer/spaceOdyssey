"""Satellite model.

Purpose: Represent maneuver-capable spacecraft and shared orbital object state.
Inputs: ECI position/velocity, mass properties, simulation metadata.
Outputs: Mutable state containers used by propagation, scheduling, and APIs.
Physical assumptions: Point-mass vehicle, impulsive burns, dry-mass floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import exp
from typing import Any

import numpy as np

DRY_MASS_KG = 500.0
INITIAL_FUEL_KG = 50.0
DEFAULT_ISP_S = 300.0
G0_MPS2 = 9.80665


class ObjectType(str, Enum):
    SATELLITE = "SATELLITE"
    DEBRIS = "DEBRIS"


class SatelliteStatus(str, Enum):
    NOMINAL = "NOMINAL"
    EVADING = "EVADING"
    RECOVERING = "RECOVERING"
    EOL = "EOL"
    COLLIDED = "COLLIDED"


@dataclass(slots=True)
class Maneuver:
    burn_id: str
    burn_time: datetime
    delta_v_eci_km_s: np.ndarray
    maneuver_type: str = "MANUAL"
    linked_cdm_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def delta_v_mps(self) -> float:
        return float(np.linalg.norm(self.delta_v_eci_km_s) * 1000.0)


@dataclass(slots=True)
class ObjectState:
    id: str
    type: ObjectType
    r: np.ndarray
    v: np.ndarray
    mass_kg: float
    fuel_kg: float
    status: SatelliteStatus
    nominal_slot_r: np.ndarray
    nominal_slot_v: np.ndarray
    cooldown_until: datetime | None
    maneuver_queue: list[Maneuver] = field(default_factory=list)
    last_updated: datetime | None = None
    recovery_checks: int = 0
    last_burn_time: datetime | None = None
    collision_count: int = 0
    active_cdms: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dry_mass_kg(self) -> float:
        return DRY_MASS_KG

    def clone(self) -> "ObjectState":
        return ObjectState(
            id=self.id,
            type=self.type,
            r=self.r.copy(),
            v=self.v.copy(),
            mass_kg=self.mass_kg,
            fuel_kg=self.fuel_kg,
            status=self.status,
            nominal_slot_r=self.nominal_slot_r.copy(),
            nominal_slot_v=self.nominal_slot_v.copy(),
            cooldown_until=self.cooldown_until,
            maneuver_queue=list(self.maneuver_queue),
            last_updated=self.last_updated,
            recovery_checks=self.recovery_checks,
            last_burn_time=self.last_burn_time,
            collision_count=self.collision_count,
            active_cdms=list(self.active_cdms),
            history=list(self.history),
        )

    def apply_delta_v(self, delta_v_eci_km_s: np.ndarray, isp_s: float = DEFAULT_ISP_S) -> float:
        delta_v_mps = float(np.linalg.norm(delta_v_eci_km_s) * 1000.0)
        propellant_used = self.compute_propellant_for_delta_v(delta_v_mps, isp_s)
        self.v = self.v + delta_v_eci_km_s
        self.fuel_kg = max(0.0, self.fuel_kg - propellant_used)
        self.mass_kg = self.dry_mass_kg + self.fuel_kg
        return propellant_used

    def compute_propellant_for_delta_v(self, delta_v_mps: float, isp_s: float = DEFAULT_ISP_S) -> float:
        current_mass = self.mass_kg
        burned = current_mass * (1.0 - exp(-abs(delta_v_mps) / (isp_s * G0_MPS2)))
        return min(burned, self.fuel_kg)


@dataclass(slots=True)
class Satellite(ObjectState):
    pass
