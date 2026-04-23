"""Simulation state container.

Purpose: Hold the in-memory constellation state, indexes, caches, and event logs.
Inputs: Telemetry batches, startup seed data, propagated object states, maneuvers.
Outputs: Shared authoritative state for APIs, autonomous services, and UI snapshots.
Physical assumptions: Centralized single-process memory model with locking.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from backend.models.cdm import CDM
from backend.models.satellite import ObjectState, ObjectType


@dataclass(slots=True)
class GroundStation:
    station_id: str
    name: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    min_elevation_deg: float


@dataclass(slots=True)
class EventRecord:
    level: str
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]


@dataclass(slots=True)
class SimState:
    current_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state_store: dict[str, ObjectState] = field(default_factory=dict)
    active_cdms: list[CDM] = field(default_factory=list)
    demo_cdms: list[CDM] = field(default_factory=list)
    ground_stations: list[GroundStation] = field(default_factory=list)
    propagation_cache: dict[int, dict[str, tuple[np.ndarray, np.ndarray]]] = field(default_factory=lambda: defaultdict(dict))
    maneuver_log: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=5000))
    collision_log: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=2000))
    event_log: deque[EventRecord] = field(default_factory=lambda: deque(maxlen=8000))
    metrics_history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=1000))
    kd_tree: cKDTree | None = None
    kd_tree_ids: list[str] = field(default_factory=list)
    autonomous_conjunctions: set[str] = field(default_factory=set)
    lock: RLock = field(default_factory=RLock)

    def upsert_object(self, obj: ObjectState) -> None:
        with self.lock:
            self.state_store[obj.id] = obj

    def get_satellites(self) -> list[ObjectState]:
        with self.lock:
            return [obj for obj in self.state_store.values() if obj.type == ObjectType.SATELLITE]

    def get_debris(self) -> list[ObjectState]:
        with self.lock:
            return [obj for obj in self.state_store.values() if obj.type == ObjectType.DEBRIS]

    def get_object(self, object_id: str) -> ObjectState | None:
        with self.lock:
            return self.state_store.get(object_id)

    def rebuild_spatial_index(self) -> None:
        with self.lock:
            ids: list[str] = []
            positions: list[np.ndarray] = []
            for object_id, obj in self.state_store.items():
                ids.append(object_id)
                positions.append(obj.r.copy())
            self.kd_tree_ids = ids
            self.kd_tree = cKDTree(np.vstack(positions)) if positions else None

    def cache_state(self, sim_time: datetime, object_id: str, r: np.ndarray, v: np.ndarray) -> None:
        self.propagation_cache[int(sim_time.timestamp())][object_id] = (r.copy(), v.copy())

    def log_event(self, level: str, event_type: str, payload: dict[str, Any]) -> None:
        self.event_log.append(EventRecord(level=level, event_type=event_type, timestamp=self.current_time, payload=payload))

    def log_maneuver(self, payload: dict[str, Any]) -> None:
        self.maneuver_log.append(payload)
        self.log_event("INFO", "maneuver", payload)

    def log_collision(self, payload: dict[str, Any]) -> None:
        self.collision_log.append(payload)
        self.log_event("CRITICAL", "collision", payload)

    def record_metrics(self, cumulative_delta_v_mps: float, collisions_avoided: int) -> None:
        self.metrics_history.append(
            {
                "timestamp": self.current_time.isoformat(),
                "cumulative_delta_v_mps": cumulative_delta_v_mps,
                "collisions_avoided": collisions_avoided,
            }
        )

    def snapshot_mass_budget(self) -> dict[str, Any]:
        sats = self.get_satellites()
        return {
            "timestamp": self.current_time.isoformat(),
            "satellite_count": len(sats),
            "fleet_fuel_kg": round(sum(s.fuel_kg for s in sats), 3),
            "fleet_mass_kg": round(sum(s.mass_kg for s in sats), 3),
            "below_eol_threshold": [s.id for s in sats if s.fuel_kg / max(s.mass_kg, 1.0) < 0.05],
        }


sim_state = SimState()
