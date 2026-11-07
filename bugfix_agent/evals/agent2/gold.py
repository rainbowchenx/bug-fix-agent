from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class GoldTicket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    defectId: str = Field(min_length=1)
    goldPaths: list[str] = Field(default_factory=list)
    matchMode: Literal["any", "all"] = "any"
    expectEmpty: bool = False


class GoldGates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requireSchemaValid: bool = True
    requirePathsExist: bool = True
    maxCandidates: int = 3
    minHitAt1: float = 0.5
    minHitAt3: float = 0.7
    minNegativeAccuracy: float = 1.0
    requireProfileHit: bool = False


class Agent2Gold(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str = "0.1.0"
    name: str = "unnamed"
    expectedProfile: list[str] = Field(default_factory=lambda: ["unknown"])
    expectedLanguagesAnyOf: Optional[list[str]] = None
    tickets: list[GoldTicket] = Field(default_factory=list)
    gates: GoldGates = Field(default_factory=GoldGates)


def parse_gold(data: Any) -> Agent2Gold:
    return Agent2Gold.model_validate(data)
