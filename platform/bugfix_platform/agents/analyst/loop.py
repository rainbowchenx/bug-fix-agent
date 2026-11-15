"""单票分析—编辑—检查循环。最多三次候选，语义复核可打回。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    EditDecision,
    Hypothesis,
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
    """对照行为目标、机制和正常/失败路径复核最终 diff。"""
    issues: list[str] = []
    blob = diff or ""
    if _HIDE.search(blob):
        issues.append("hides error")
    if _DROP_ASSERT.search(blob):
        issues.append("deleted assertion")
    expected = ""
    if context.revision is not None:
        expected = context.revision.expected or ""
    haystack = " ".join(
        part
        for part in [
            decision.mechanism,
            decision.behaviorTarget,
            expected,
            decision.editRationale,
        ]
        if part
    )
    paths = re.findall(r"[\w./\\]+\.\w+", decision.codeAssociation or "")
    blob_norm = blob.replace("\\", "/")
    if paths and not any(p.replace("\\", "/") in blob_norm for p in paths):
        issues.append("patch does not touch associated code")
    code = _changed_source(blob)
    if _has_edits(blob) and not code.strip():
        issues.append("comment-only change")
    surface = f"{code}\n{_hunk_context(blob)}".lower()
    skip = {"error", "errors", "after", "before", "using", "with", "from", "this", "that", "other"}
    idents = [
        tok
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", haystack)
        if tok.lower() not in skip
    ]
    if idents and not any(tok.lower() in surface for tok in idents):
        issues.append("patch does not address mechanism")
    return issues


def review_conclusion(
    diff: str,
    context: TaskContext,
    decision: EditDecision,
    *,
    model_text: str | None = None,
    status: str | None = None,
) -> str:
    """记录模型对最终 diff 的复核；未执行则如实标记。"""
    judged = str(model_text or "").strip()
    st = str(status or "").strip().lower()
    if st == "failed":
        return judged or "semantic review failed"
    if st == "passed":
        return judged or "semantic review passed"
    return judged if judged and "not executed" in judged.lower() else "semantic review not executed"


def _has_edits(diff: str) -> bool:
    return any(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        for line in (diff or "").splitlines()
    )


def _changed_source(diff: str) -> str:
    lines: list[str] = []
    for line in (diff or "").splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        body = line[1:]
        stripped = body.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "/*", "*/")):
            continue
        lines.append(body)
    return "\n".join(lines)


def _hunk_context(diff: str) -> str:
    """@@ 头里的函数名算机制上下文；不含 diff --git / --- / +++ 路径。"""
    return "\n".join(
        line for line in (diff or "").splitlines() if line.startswith("@@")
    )


def run_ticket(
    context: TaskContext,
    services: Mapping[str, Callable[..., Any]],
    *,
    attempt_id: str | None = None,
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
    attempt_id = attempt_id or uuid4().hex[:12]
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
    review_fn = services.get("review")
    last_diff = ""
    last_patch: PatchSet | None = None
    checks: list[VerificationRun] = []
    produced = False
    last_review = {"status": "not_executed", "text": ""}
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
        if check is not None:
            raw = check(context, decision, last_patch)
            runs = _as_checks(raw)
            checks.extend(runs)
            if not runs or _checks_failed(runs):
                produced = False
                feedback: list[Hypothesis] = []
                for item in runs or [
                    VerificationRun(command=["check"], result="blocked", coverage="no_runs")
                ]:
                    claim = " ".join(
                        part
                        for part in [
                            f"check {item.result}",
                            " ".join(item.command),
                            _log_excerpt(item),
                        ]
                        if part
                    )
                    feedback.append(
                        Hypothesis(claim=claim[:240] or "check failed", status="refuted")
                    )
                context = context.model_copy(
                    update={"hypotheses": list(context.hypotheses) + feedback}
                )
                continue
        last_review = _as_review(
            review_fn(last_diff, context, decision) if review_fn is not None else None
        )
        decision = decision.model_copy(
            update={
                "executionPremise": review_conclusion(
                    last_diff,
                    context,
                    decision,
                    model_text=last_review.get("text"),
                    status=last_review.get("status"),
                ),
            }
        )
        if last_review.get("status") == "failed":
            produced = False
            context = context.model_copy(
                update={
                    "hypotheses": list(context.hypotheses)
                    + [
                        Hypothesis(
                            claim=f"semantic review failed: {last_review.get('text') or ''}"[:240],
                            status="refuted",
                        )
                    ]
                }
            )
            continue
        produced = True
        break
    if produced and last_patch is None and last_diff.strip():
        last_patch = _synthetic_patch(last_diff)
    if produced and last_patch is not None and last_patch.patches:
        delivery = last_patch.delivery if last_patch.delivery != "none" else "candidate"
        if delivery == "candidate":
            last_patch = last_patch.model_copy(update={"delivery": "candidate"})
            resolution = "patch_produced"
        else:
            resolution = "analysis_only"
    elif last_patch is not None and last_patch.patches and last_review.get("status") == "failed":
        last_patch = last_patch.model_copy(update={"delivery": "diagnostic"})
        resolution = "analysis_only"
        delivery = "diagnostic"
        produced = False
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


def _as_review(raw: Any) -> dict[str, str]:
    if raw is None:
        return {"status": "not_executed", "text": ""}
    if isinstance(raw, str):
        text = raw.strip()
        low = text.lower()
        if not text or "not executed" in low or "未执行" in text:
            return {"status": "not_executed", "text": text or "semantic review not executed"}
        return {"status": "passed", "text": text}
    if isinstance(raw, dict):
        text = str(raw.get("text") or raw.get("semanticReview") or "").strip()
        status = str(raw.get("status") or raw.get("semanticReviewStatus") or "").strip().lower()
        if status in {"failed", "fail"}:
            return {"status": "failed", "text": text}
        if status in {"not_executed", "skipped"}:
            return {"status": "not_executed", "text": text}
        if status in {"passed", "pass"}:
            return {"status": "passed", "text": text}
        if not text:
            return {"status": "not_executed", "text": ""}
        return {"status": "passed", "text": text}
    return {"status": "not_executed", "text": ""}


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


def _log_excerpt(item: VerificationRun) -> str:
    ref = item.logRef or ""
    if not ref:
        return item.coverage or ""
    path = Path(ref)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")[:400]
    return ref


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
