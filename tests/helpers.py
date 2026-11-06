"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

from bugfix_agent.contracts import DefectBatch
from bugfix_agent.defect_batch import run_defect_batch_prepare

ROOT = Path(__file__).resolve().parents[1]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


def defect_batch_from_hc1(*, posture: str = "alpha") -> DefectBatch:
    return run_defect_batch_prepare(
        product_line="hc",
        source=HC1,
        posture=posture,  # type: ignore[arg-type]
    )


def minimal_defect_batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-11-05T00:00:00Z",
            "funnel": {"total": 0},
            "clusters": [],
            "tickets": [],
        }
    )
