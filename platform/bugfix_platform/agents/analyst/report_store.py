"""汇总 analysis-report：优先读完整文件，损坏时从逐票快照重建。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.analysis_report import AnalysisReport, validate_analysis_report
from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot
from bugfix_platform.agents.analyst.sessions import load_latest_attempt


def load_analysis_report(root: Path | str, *, allow_rebuild_on_error: bool = True) -> Optional[AnalysisReport]:
    """读取汇总报告。

    JSON 截断/损坏返回 None 以便重建；不支持的 schemaVersion 仍抛出，避免误用旧汇总。
    """
    path = Path(root) / "analysis-report.json"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return validate_analysis_report(data)
    except (ValueError, TypeError) as err:
        if "schemaVersion" in str(err):
            raise
        if allow_rebuild_on_error:
            return None
        raise


def rebuild_analysis_report_from_snapshots(
    root: Path | str,
    *,
    product_line: str = "",
    work_dir: str = "",
    apply_fix: bool = False,
) -> Optional[AnalysisReport]:
    """用各票 latest 指向的 analysis 快照重建汇总，跳过损坏票。"""
    base = Path(root)
    defects = base / "defects"
    if not defects.is_dir():
        return None
    tickets: list[dict[str, Any]] = []
    for folder in sorted(defects.iterdir()):
        if not folder.is_dir():
            continue
        defect_id = folder.name
        latest = load_latest_attempt(base, defect_id)
        if latest is None:
            continue
        try:
            snap = load_analysis_snapshot(base, defect_id, latest.attemptId)
        except (OSError, ValueError, TypeError):
            continue
        tickets.append(snap.ticketReport.model_dump())
    if not tickets:
        return None
    by_outcome: dict[str, int] = {}
    for item in tickets:
        oc = str(item.get("outcome") or "other_blocked")
        by_outcome[oc] = by_outcome.get(oc, 0) + 1
    payload = {
        "schemaVersion": "0.4.0",
        "productLine": product_line or "unknown",
        "workDir": work_dir or str(base),
        "generatedAt": "1970-01-01T00:00:00Z",
        "openMr": False,
        "applyFix": apply_fix,
        "integrateMode": "none",
        "summary": {"total": len(tickets), "byOutcome": by_outcome},
        "tickets": tickets,
    }
    try:
        return validate_analysis_report(payload)
    except (ValueError, TypeError):
        return None


def load_or_rebuild_analysis_report(
    root: Path | str,
    *,
    product_line: str = "",
    work_dir: str = "",
    apply_fix: bool = False,
) -> Optional[AnalysisReport]:
    """完整汇总优先；损坏或缺失时从逐票快照重建。"""
    report = load_analysis_report(root)
    if report is not None:
        return report
    return rebuild_analysis_report_from_snapshots(
        root,
        product_line=product_line,
        work_dir=work_dir,
        apply_fix=apply_fix,
    )
