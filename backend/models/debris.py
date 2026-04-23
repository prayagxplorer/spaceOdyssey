"""Debris model.

Purpose: Represent passive tracked debris objects in the simulation.
Inputs: ECI position/velocity vectors and tracking metadata.
Outputs: Shared object-state instances used for conjunction assessment.
Physical assumptions: Non-maneuvering point masses with no fuel consumption.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.models.satellite import ObjectState


@dataclass(slots=True)
class Debris(ObjectState):
    pass
