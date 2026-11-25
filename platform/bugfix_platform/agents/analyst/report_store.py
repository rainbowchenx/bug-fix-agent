"""协调已提交的逐票快照与派生汇总。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.analysis_report import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    validate_analysis_report,
)
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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    try:
        return validate_analysis_report(data)
    except (ValueError, TypeError):
        version = data.get("schemaVersion") if isinstance(data, dict) else None
        if not allow_rebuild_on_error or (
            isinstance(version, str) and version != ANALYSIS_REPORT_SCHEMA_VERSION
        ):
            raise
        return None


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
        "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
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
    """以已提交快照更新汇总，保留没有快照的现有条目。"""
    report = load_analysis_report(root)
    committed = rebuild_analysis_report_from_snapshots(
        root,
        product_line=product_line,
        work_dir=work_dir,
        apply_fix=apply_fix,
    )
    if report is None or committed is None:
        return committed or report
    return merge_analysis_report(committed, report, keep_previous_metadata=True)


def merge_analysis_report(
    current: AnalysisReport,
    previous: AnalysisReport | None,
    *,
    keep_previous_metadata: bool = False,
) -> AnalysisReport:
    tickets = {ticket.defectId: ticket for ticket in previous.tickets} if previous else {}
    tickets.update((ticket.defectId, ticket) for ticket in current.tickets)
    metadata = previous if keep_previous_metadata and previous is not None else current
    payload = metadata.model_dump()
    payload["tickets"] = list(tickets.values())
    payload["summary"] = {
        "total": len(tickets),
        "byOutcome": dict(Counter(ticket.outcome for ticket in tickets.values())),
    }
    return validate_analysis_report(payload)


def atomic_write_report(path: Path, text: str) -> None:
    """Publish a complete report file while the caller holds the artifact lock."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def publish_analysis_report(root: Path, report: AnalysisReport, *, already_locked: bool = False) -> None:
    from contextlib import nullcontext

    from bugfix_platform.agents.analyst.attempt_store import store_lock
    from bugfix_platform.agents.analyst.report import render_analysis_markdown

    with nullcontext() if already_locked else store_lock(root):
        atomic_write_report(root / "analysis-report.json", report.model_dump_json(indent=2))
        atomic_write_report(root / "analysis-report.md", render_analysis_markdown(report))
