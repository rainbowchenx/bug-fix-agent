"""规则管线之后的意图复核：把模型调整写回 ``defect-batch`` 并重建簇。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator

from bugfix_agent.contracts.common import MATCH_POOLS, Confidence
from bugfix_agent.contracts.defect_batch import (
    DefectBatch,
    ExpectQuality,
    Intent,
    Pool,
    validate_defect_batch,
)
from bugfix_agent.defect_batch.cluster import rebuild_clusters_from_tickets

PROTECTED_POOLS = frozenset({"hard_reject", "security", "excluded", "duplicate"})
STRICT_EXPECT = frozenset({"explicit", "inferred"})


class IntentOverride(BaseModel):
    """单张票的意图 / 功能池调整。"""

    model_config = ConfigDict(extra="forbid")

    defectId: str
    intent: Optional[Intent] = None
    intentRationale: Optional[str] = None
    intentConfidence: Optional[Confidence] = None
    pool: Optional[Pool] = None
    expectQuality: Optional[ExpectQuality] = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> IntentOverride:
        if self.intent is None and self.pool is None and self.expectQuality is None:
            raise ValueError("adjustment needs intent, pool, or expectQuality")
        return self


class IntentReviewFile(BaseModel):
    """Skill 落盘的复核文件。"""

    model_config = ConfigDict(extra="ignore")

    adjustments: list[IntentOverride]


def apply_intent_review(
    batch: DefectBatch,
    overrides: Sequence[Union[IntentOverride, dict[str, Any]]],
) -> DefectBatch:
    """把意图复核写回批次：改票、重建簇与漏斗、再校验。

    只允许在匹配池（``strict`` / ``locatable_only`` / ``needs_info``）内调整。
    硬淘汰池（``hard_reject`` / ``security`` / ``excluded`` / ``duplicate``）
    不可移入也不可移出。升入 ``strict`` 时 ``expectQuality`` 必须是
    ``explicit`` 或 ``inferred``。

    Args:
        batch: 规则管线产出的批次。
        overrides: 调整列表，或同结构的 dict。

    Returns:
        校验通过的新 ``DefectBatch``（不修改入参）。

    Raises:
        ValueError: 未知票、受保护池、或升入 strict 时预期质量不够。
        ValidationError: 调整项字段不合法。
    """
    parsed = [
        item if isinstance(item, IntentOverride) else IntentOverride.model_validate(item)
        for item in overrides
    ]
    by_id = {t.defectId: t.model_copy(deep=True) for t in batch.tickets}
    for item in parsed:
        ticket = by_id.get(item.defectId)
        if ticket is None:
            raise ValueError(f"unknown defectId {item.defectId!r}")
        if ticket.pool in PROTECTED_POOLS:
            raise ValueError(
                f"cannot review-adjust ticket {item.defectId} in protected pool {ticket.pool}"
            )
        if item.pool is not None:
            if item.pool in PROTECTED_POOLS or item.pool not in MATCH_POOLS:
                raise ValueError(
                    f"cannot move {item.defectId} into protected or unknown pool {item.pool}"
                )
            ticket.pool = item.pool
        if item.expectQuality is not None:
            ticket.expectQuality = item.expectQuality
        if ticket.pool == "strict" and ticket.expectQuality not in STRICT_EXPECT:
            raise ValueError(
                f"{item.defectId}: strict requires expectQuality explicit or inferred"
            )
        if item.intent is not None:
            ticket.intent = item.intent
            ticket.intentSource = "ai"
            ticket.intentConfidence = item.intentConfidence or "high"
            if item.intentRationale:
                ticket.intentRationale = item.intentRationale
        elif item.intentRationale:
            ticket.intentRationale = item.intentRationale
            if ticket.intent is not None:
                ticket.intentSource = "ai"

    tickets = list(by_id.values())
    clusters = rebuild_clusters_from_tickets(tickets, batch.productLine)
    updated = batch.model_copy(
        update={
            "tickets": tickets,
            "clusters": clusters,
            "funnel": _funnel_from_tickets(tickets),
        }
    )
    return validate_defect_batch(updated.model_dump())


def _funnel_from_tickets(tickets: Sequence[Any]) -> dict[str, int]:
    out = {
        "total": len(tickets),
        "strict": 0,
        "locatable_only": 0,
        "needs_info": 0,
        "hard_reject": 0,
        "security": 0,
        "excluded": 0,
        "duplicate": 0,
    }
    for ticket in tickets:
        pool = ticket.pool
        out[pool] = out.get(pool, 0) + 1
    return out
