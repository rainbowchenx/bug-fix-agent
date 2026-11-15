"""单票分析—编辑—检查循环。最多三次候选，语义复核可打回。"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    EditDecision,
    TaskContext,
)

_HIDE = re.compile(
    r"catch\s*\([^)]*\)\s*\{\s*\}|pytest\.mark\.skip|\bxit\(|it\.skip\(",
    re.I,
)
_DROP_ASSERT = re.compile(r"^-.*\b(assert|expect|should)\b", re.M)


def semantic_review(
    diff: str,
    context: TaskContext,
    decision: EditDecision,
) -> list[str]:
    """最终 diff 的机制复核。命中则不能作为合格候选。"""
    issues: list[str] = []
    if _HIDE.search(diff or ""):
        issues.append("hides error")
    if _DROP_ASSERT.search(diff or ""):
        issues.append("deleted assertion")
    return issues


def run_ticket(
    context: TaskContext,
    services: Mapping[str, Callable[..., Any]],
) -> AttemptRecord:
    """注入 analyze/edit/check/save。无充分证据则分析收尾。"""
    analyze = services["analyze"]
    decision = analyze(context)
    if not isinstance(decision, EditDecision):
        decision = EditDecision.model_validate(decision)
    attempt_id = uuid4().hex[:12]
    if not context.generatePatch or not decision.allowed:
        return AttemptRecord(
            schemaVersion=REPAIR_SCHEMA_VERSION,
            attemptId=attempt_id,
            defectId=context.defectId,
            execution="completed",
            resolution="needs_information" if not decision.allowed else "analysis_only",
            patchDelivery="none",
            editDecision=decision,
        )
    edit = services.get("edit")
    check = services.get("check")
    save = services.get("save")
    last_diff = ""
    for _ in range(3):
        if edit is not None:
            produced = edit(context, decision)
            last_diff = ""
            if isinstance(produced, str):
                last_diff = produced
            elif isinstance(produced, dict):
                last_diff = str(produced.get("diff") or "")
        issues = semantic_review(last_diff, context, decision)
        if issues:
            decision = EditDecision.model_validate(
                {**decision.model_dump(), "allowed": False, "reason": "; ".join(issues)}
            )
            break
        if check is not None:
            check(context, decision)
        break
    if save is not None:
        save(context, decision)
    produced = bool(decision.allowed)
    return AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId=attempt_id,
        defectId=context.defectId,
        execution="completed",
        resolution="patch_produced" if produced else "analysis_only",
        patchDelivery="candidate" if produced else "none",
        editDecision=decision,
    )
