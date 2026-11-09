"""Agent-1 规则管线编排：蒸馏 → 筛选 → 分簇 → 组装 ``DefectBatch``。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from bugfix_contracts.defect_batch import (
    DEFECT_BATCH_SCHEMA_VERSION,
    DefectBatch,
    RawDefect,
    validate_defect_batch,
)
from bugfix_agent1.defect_batch.cluster import cluster_screened
from bugfix_agent1.defect_batch.distill import distill_all
from bugfix_agent1.defect_batch.intent import IntentClassifier
from bugfix_agent1.defect_batch.rules import ScreenProfile
from bugfix_agent1.defect_batch.screen import funnel_counts, screen_all


def prepare_defect_batch(
    *,
    product_line: str,
    defects: list[RawDefect],
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
    intent_classifier: Optional[IntentClassifier] = None,
    validate: bool = True,
) -> DefectBatch:
    """从已归一的 ``RawDefect`` 制备并（默认）校验 ``defect-batch``。

    管线为纯规则：蒸馏 / R0–R3 筛选 / L1–L2 分簇 + L3 意图（默认识别器不调
    LLM）。不负责 Ingest；调用方须先得到 ``defects``。

    Args:
        product_line: 产品线标识，写入产物并参与 ``clusterId``。
        defects: 已归一的原始缺陷列表（``raw-defects`` 边界之后）。
        posture: 筛选姿态。``beta`` 时非 Open/New 进 ``excluded``。
        profile: 可选筛池规则覆盖；默认 ``ScreenProfile()``。
        intent_classifier: L3 意图分类器。默认启发式
            ``default_intent_classifier``。
        validate: 为 True 时经 ``validate_defect_batch`` 再返回。

    Returns:
        组装好的 ``DefectBatch``；``validate=True`` 时为校验后的模型。
    """
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
