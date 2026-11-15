"""单票分析—编辑—检查循环。最多三次候选，语义复核可打回。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    EditDecision,
    PatchFile,
    PatchSet,
    TaskContext,
    VerificationRun,
)
from bugfix_platform.agents.analyst.evidence import validate_edit_decision

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
    """注入 analyze/edit/check/save。空 diff / 检查失败不能当候选。"""
    analyze = services["analyze"]
    decision = analyze(context)
    if not isinstance(decision, EditDecision):
        decision = EditDecision.model_validate(decision)
    errors = validate_edit_decision(context, decision)
    if errors:
        decision = EditDecision.model_validate(
            {**decision.model_dump(), "allowed": False, "reason": "; ".join(errors)}
        )
    attempt_id = uuid4().hex[:12]
    revision_id = context.revision.revisionId if context.revision else None
    if not context.generatePatch or not decision.allowed:
        return AttemptRecord(
            schemaVersion=REPAIR_SCHEMA_VERSION,
            attemptId=attempt_id,
            defectId=context.defectId,
            revisionId=revision_id,
            execution="completed",
            resolution="needs_information" if not decision.allowed else "analysis_only",
            patchDelivery="none",
            editDecision=decision,
            evidence=list(context.evidence),
        )
    edit = services.get("edit")
    check = services.get("check")
    save = services.get("save")
    last_diff = ""
    last_patch: PatchSet | None = None
    checks: list[VerificationRun] = []
    produced = False
    for _ in range(3):
        produced_edit = edit(context, decision) if edit is not None else None
        last_diff, last_patch = _unpack_edit(produced_edit)
        if not last_diff.strip() and (last_patch is None or not last_patch.patches):
            decision = EditDecision.model_validate(
                {**decision.model_dump(), "allowed": False, "reason": "empty diff"}
            )
            produced = False
            break
        issues = semantic_review(last_diff, context, decision)
        if issues:
            decision = EditDecision.model_validate(
                {**decision.model_dump(), "allowed": False, "reason": "; ".join(issues)}
            )
            produced = False
            continue
        if check is None:
            produced = True
            break
        raw = check(context, decision, last_patch)
        runs = _as_checks(raw)
        checks.extend(runs)
        if not runs or _checks_failed(runs):
            produced = False
            continue
        produced = True
        break
    if produced and last_patch is None and last_diff.strip():
        last_patch = _synthetic_patch(last_diff)
    if produced and last_patch is not None and last_patch.patches:
        last_patch = last_patch.model_copy(update={"delivery": "candidate"})
        resolution = "patch_produced"
        delivery = "candidate"
    else:
        last_patch = None
        resolution = "analysis_only"
        delivery = "none"
        produced = False
    if save is not None:
        save(context, decision)
    return AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId=attempt_id,
        defectId=context.defectId,
        revisionId=revision_id,
        execution="completed",
        resolution=resolution,
        patchDelivery=delivery,
        editDecision=decision,
        patchSet=last_patch,
        checks=checks,
        evidence=list(context.evidence),
    )


def _unpack_edit(produced: Any) -> tuple[str, PatchSet | None]:
    if produced is None:
        return "", None
    if isinstance(produced, PatchSet):
        return ("x" if produced.patches else ""), produced
    if isinstance(produced, str):
        return produced, None
    if isinstance(produced, dict):
        diff = str(produced.get("diff") or "")
        patch = produced.get("patchSet")
        if isinstance(patch, PatchSet):
            return diff or ("x" if patch.patches else ""), patch
        return diff, None
    return "", None


def _as_checks(raw: Any) -> list[VerificationRun]:
    if raw is None:
        return []
    if isinstance(raw, VerificationRun):
        return [raw]
    if isinstance(raw, list):
        return [VerificationRun.model_validate(x) if not isinstance(x, VerificationRun) else x for x in raw]
    try:
        return [VerificationRun.model_validate(raw)]
    except Exception:  # noqa: BLE001
        return []


def _checks_failed(runs: list[VerificationRun]) -> bool:
    return any(item.result in {"failed", "blocked"} for item in runs)


def _synthetic_patch(diff: str) -> PatchSet:
    digest = hashlib.sha256(diff.encode("utf-8")).hexdigest()[:16]
    return PatchSet(
        patchSetId=uuid4().hex[:12],
        delivery="candidate",
        patches=[
            PatchFile(
                path="repair.diff",
                kind="modify",
                digest=digest,
                archivePath="repair.diff",
            )
        ],
    )
