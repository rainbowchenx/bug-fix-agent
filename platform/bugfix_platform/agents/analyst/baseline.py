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


def _truthy_required(case: dict[str, Any]) -> bool:
    value = case.get("requiredQuestion")
    if value is None:
        value = case.get("requiredQuestions")
    if isinstance(value, list):
        return bool(value)
    return bool(value)


def _truthy_consumed(case: dict[str, Any]) -> bool:
    if "answerConsumed" in case:
        return bool(case.get("answerConsumed"))
    if "answersConsumed" in case:
        raw = case.get("answersConsumed")
        if isinstance(raw, (int, float)):
            return raw > 0
        return bool(raw)
    return False


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
            if case.get("ratingStatus") == "stale" and prev is not None and prev.get("ratingStatus") != "stale":
                continue
            by_defect[key] = case
    rows = list(by_defect.values())
    n = len(rows)
    live = [c for c in rows if c.get("ratingStatus") != "stale"]
    success = sum(1 for c in live if c.get("accepted") is True and c.get("resolved") is True)
    failed = sum(1 for c in live if c.get("accepted") is True and c.get("resolved") is False)
    pending = sum(1 for c in live if c.get("status") == "pending" or c.get("accepted") is None)
    report_only = True if apply_fix is False else (False if apply_fix is True else (all(c.get("applyFix") is False for c in rows) if rows else True))
    observed_den = success + failed
    required = [c for c in live if _truthy_required(c)]
    answered = sum(1 for c in required if _truthy_consumed(c))
    reopened = sum(1 for c in live if c.get("questionReopened"))
    return {
        "uniqueDefects": n,
        "success": success,
        "failed": failed,
        "pending": pending,
        "stale": sum(1 for c in rows if c.get("ratingStatus") == "stale"),
        "conservativeRate": (success / n) if n else None,
        "observedRate": (success / observed_den) if observed_den else None,
        "repairRate": None if report_only else ((success / n) if n else None),
        "answerConsumption": (answered / len(required)) if required else None,
        "repeatQuestionRate": (reopened / n) if n else None,
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
