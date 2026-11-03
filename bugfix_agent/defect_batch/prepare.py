from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from bugfix_agent.contracts.defect_batch import (
    DEFECT_BATCH_SCHEMA_VERSION,
    DefectBatch,
    RawDefect,
    validate_defect_batch,
)
from bugfix_agent.defect_batch.cluster import cluster_screened
from bugfix_agent.defect_batch.distill import distill_all
from bugfix_agent.defect_batch.intent import IntentClassifier
from bugfix_agent.defect_batch.rules import ScreenProfile
from bugfix_agent.defect_batch.screen import funnel_counts, screen_all


def prepare_defect_batch(
    *,
    product_line: str,
    defects: list[RawDefect],
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
    intent_classifier: Optional[IntentClassifier] = None,
    validate: bool = True,
) -> DefectBatch:
    digests = distill_all(defects)
    screened = screen_all(digests, posture=posture, profile=profile)
    clusters, tickets = cluster_screened(
        screened,
        product_line,
        intent_classifier=intent_classifier,
    )
    batch = DefectBatch(
        schemaVersion=DEFECT_BATCH_SCHEMA_VERSION,
        productLine=product_line,
        posture=posture,
        generatedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        funnel=funnel_counts(screened),
        clusters=clusters,
        tickets=tickets,
    )
    if not validate:
        return batch
    return validate_defect_batch(batch.model_dump())
