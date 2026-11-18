"""T00：修复闭环基线清单。不把环境缺口当新回归，无验收数据不打成功率。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

from bugfix_contracts.common import CONTRACT_SCHEMA_VERSION

REPAIR_CASE_KINDS = (
    "wrong_argument",
    "missing_failure_state",
    "needs_attachment",
    "out_of_repo",
)

# 本机常见、与本计划无关的失败：缺 optional SDK extra。
_PREEXISTING_NODE_MARKERS = (
    "tests/platform/test_sdk_billing.py",
)


def attribute_test_failures(failed_nodeids: Iterable[str]) -> dict[str, list[str]]:
    """把失败拆成 preexisting / new。现有环境缺口先归因。"""
    preexisting: list[str] = []
    new: list[str] = []
    for node in failed_nodeids:
        text = str(node).replace("\\", "/")
        if any(m in text for m in _PREEXISTING_NODE_MARKERS):
            preexisting.append(str(node))
        else:
            new.append(str(node))
    return {"preexisting": preexisting, "new": new}


def _question_counts(case: dict[str, Any]) -> tuple[int, int]:
    required = case.get("requiredQuestions")
    if required is None:
        required = case.get("requiredQuestion")
    if isinstance(required, list):
        n_req = len([item for item in required if item])
    elif isinstance(required, (int, float)):
        n_req = int(required)
    elif required:
        n_req = 1
    else:
        n_req = 0
    consumed = case.get("answersConsumed")
    if consumed is None:
        consumed = case.get("answerConsumed")
    if isinstance(consumed, (int, float)):
        n_cons = int(consumed)
    elif consumed:
        n_cons = n_req or 1
    else:
        n_cons = 0
    return n_req, n_cons


def _effective_answer_counts(case: dict[str, Any]) -> tuple[int, int] | None:
    """没有独立录入的有效答案数时保留未知。"""
    _, handled = _question_counts(case)
    raw = case.get("effectiveAnswers")
    if raw is None:
        raw = case.get("answersProvided")
    if isinstance(raw, list):
        received = sum(bool(item) for item in raw)
    elif isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        received = raw
    else:
        return None
    return received, min(max(handled, 0), received)


def _reopen_counts(case: dict[str, Any]) -> tuple[int, int]:
    unjustified = int(case.get("unjustifiedReopens") or 0)
    justified = int(case.get("justifiedReopens") or 0)
    if unjustified == 0 and justified == 0 and case.get("questionReopened"):
        unjustified = 1
    return unjustified, justified


def _eligibility(case: dict[str, Any]) -> bool | None:
    for field in ("eligible", "repairEligible", "eligibility"):
        value = case.get(field)
        if isinstance(value, bool):
            return value
    return None


def convergence_metrics(
    cases: list[dict[str, Any]],
    *,
    apply_fix: bool | None = None,
) -> dict[str, Any]:
    """固定分母计分。pending 独立统计，stale 占分母但不继承成功。"""
    by_defect: dict[str, dict[str, Any]] = {}
    for case in cases:
        did = str(case.get("defectId") or case.get("id") or "")
        if not did:
            continue
        product = str(case.get("product") or case.get("productLine") or "")
        key = f"{product}:{did}"
        prev = by_defect.get(key)
        if prev is None or int(case.get("attemptSeq") or 0) >= int(prev.get("attemptSeq") or 0):
            by_defect[key] = case
    rows = list(by_defect.values())
    n = len(rows)
    live = [c for c in rows if c.get("ratingStatus") != "stale"]
    success = sum(1 for c in live if c.get("accepted") is True and c.get("resolved") is True)
    failed = sum(1 for c in live if c.get("accepted") is True and c.get("resolved") is False)
    pending = sum(1 for c in live if c.get("status") == "pending" or c.get("accepted") is None)
    report_only = True if apply_fix is False else (False if apply_fix is True else (all(c.get("applyFix") is False for c in rows) if rows else True))
    observed_den = success + failed
    req_total = 0
    effective_total = 0
    handled_total = 0
    unjustified_total = 0
    justified_total = 0
    missing_answer_denominator = False
    for case in live:
        n_req, _ = _question_counts(case)
        req_total += n_req
        answer_counts = _effective_answer_counts(case)
        if answer_counts is not None:
            received, handled = answer_counts
            effective_total += received
            handled_total += handled
        elif case.get("answersConsumed") is not None or case.get("answerConsumed") is not None:
            missing_answer_denominator = True
        uj, jr = _reopen_counts(case)
        unjustified_total += uj
        justified_total += jr
    reopen_den = unjustified_total + justified_total
    has_eligibility = any(_eligibility(c) is not None for c in rows)
    eligible = [c for c in rows if _eligibility(c) is True]
    eligible_success = sum(
        1 for c in eligible
        if c.get("ratingStatus") not in {"stale", "unbound"}
        and c.get("accepted") is True and c.get("resolved") is True
    )
    return {
        "uniqueDefects": n,
        "success": success,
        "failed": failed,
        "pending": pending,
        "stale": sum(1 for c in rows if c.get("ratingStatus") == "stale"),
        "conservativeRate": (success / n) if n and not report_only else None,
        "observedRate": (success / observed_den) if observed_den and not report_only else None,
        "repairRate": None if report_only else ((success / n) if n else None),
        "answerConsumption": (handled_total / effective_total) if effective_total and not missing_answer_denominator else None,
        "repeatQuestionRate": (unjustified_total / req_total) if req_total else None,
        "justifiedReopenRate": (justified_total / reopen_den) if reopen_den else None,
        "eligibleDefects": len(eligible) if has_eligibility else None,
        "eligibleRepairRate": (eligible_success / len(eligible)) if eligible and not report_only else None,
        "note": "70% is a proposed repair-ticket SLA, not an engineering bar",
    }


def repair_success_metrics(
    *,
    accepted: int = 0,
    resolved: int = 0,
    reported: int = 0,
) -> dict[str, Any]:
    """没有用户验收数据时不生成成功率。"""
    payload: dict[str, Any] = {
        "accepted": accepted,
        "resolved": resolved,
        "reported": reported,
        "denominator": reported,
        "successRate": None,
        "reason": None,
    }
    if accepted <= 0:
        payload["reason"] = "no_acceptance_data"
        return payload
    payload["successRate"] = resolved / accepted
    payload["reason"] = None
    return payload


def collect_repair_baseline(root: str | Path) -> dict[str, Any]:
    """记录 Python / 契约版本 / git / 夹具种类，不在业务仓装依赖。"""
    root_path = Path(root)
    head = _git_head(root_path)
    return {
        "python": sys.version.split()[0],
        "schemaVersion": CONTRACT_SCHEMA_VERSION,
        "gitHead": head,
        "limits": {
            "analyzeMaxTurnsDefault": 24,
            "promptTicketsMax": 16,
            "applyFixDefault": False,
        },
        "fixtureKinds": list(REPAIR_CASE_KINDS),
        "preexistingFailureMarkers": list(_PREEXISTING_NODE_MARKERS),
    }


def _git_head(root: Path) -> str | None:
    head_file = root / ".git" / "HEAD"
    if not head_file.is_file():
        return None
    try:
        text = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text.startswith("ref:"):
        ref = text.split(":", 1)[1].strip()
        ref_file = root / ".git" / ref
        if ref_file.is_file():
            try:
                return ref_file.read_text(encoding="utf-8").strip()[:40]
            except OSError:
                return ref
        return ref
    return text[:40]
