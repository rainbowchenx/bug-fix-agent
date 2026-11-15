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
