"""Conjunction Data Message model.

Purpose: Carry conjunction-risk outputs from coarse search through UI/API layers.
Inputs: Satellite/debris candidate states and forward-propagated encounter geometry.
Outputs: Immutable warning records sorted and queried by downstream services.
Physical assumptions: Simplified collision probability based on miss distance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(slots=True)
class CDM:
    sat_id: str
    deb_id: str
    tca: datetime
    miss_distance_km: float
    Pc: float
    approach_vector: np.ndarray
    created_at: datetime
    coarse_distance_km: float
    cdm_id: str = field(init=False)

    def __post_init__(self) -> None:
        stamp = int(self.tca.timestamp())
        self.cdm_id = f"{self.sat_id}:{self.deb_id}:{stamp}"

    @property
    def risk(self) -> str:
        if self.miss_distance_km < 1.0 or self.Pc > 1e-2:
            return "RED"
        if self.miss_distance_km < 5.0 or self.Pc > 1e-4:
            return "YELLOW"
        return "GREEN"
