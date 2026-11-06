from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bugfix_agent.agents.analyst.route import route_ticket, slice_ticket
from bugfix_agent.contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_analysis_report,
)
from bugfix_agent.contracts.analysis_report import TicketReport
from bugfix_agent.sdk.analyze import (
    AnalyzeRequest,
    AnalyzeRunner,
    analyze_mode_from_env,
    create_analyze_runner,
)


def run_analyst(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    code_knowledge: CodeKnowledge,
    open_mr: bool = False,
    analyze_mode: Optional[str] = None,
    analyze_fn: Optional[AnalyzeRunner] = None,
    analyze_limit: Optional[int] = None,
) -> AnalysisReport:
    """Agent-3 公开入口：产出 ``analysis-report``（默认只出报告、不开 MR）。

    对匹配池中的每张票::

        route_ticket（确定性）──► 可选 analyze 会话（heuristic|sdk）
                              └──► 非法票行降级为 other_blocked

    - ``needs_ticket_info`` / ``unlocalized`` 停在路由器（不调 LLM）。
    - 软定位票（``plan_only`` 提示）可进入 analyze。
    - 单票校验失败 → ``other_blocked``，整份报告仍继续。
    - 当前 ``open_mr`` 只改报告标志，不会真推 GitLab。
    """
    work_dir = str(work_dir)
    match_by_id = {m.defectId: m for m in code_knowledge.defectCodeMatches}
    runner = analyze_fn or create_analyze_runner(analyze_mode_from_env(analyze_mode))
    remaining = analyze_limit if analyze_limit is not None else _limit_from_env()

    tickets: list[dict[str, Any]] = []
    for t in defect_batch.tickets:
        if not is_match_pool(t.pool):
            continue
        # 先确定性路由；仅当路由器给出 plan_only 时才进 analyze。
        routed = route_ticket(t, match_by_id.get(t.defectId))
        entry: dict[str, Any] = {
            "defectId": t.defectId,
            "ticket": slice_ticket(t),
            **routed,
        }

        if routed["outcome"] == "plan_only" and (remaining is None or remaining > 0):
            result = runner(AnalyzeRequest(work_dir=work_dir, ticket=t, routed=routed))
            entry.update(result.payload)
            loc = dict(entry.get("localization") or {})
            note_bits = [x for x in [loc.get("notes"), f"analyze={result.source}"] if x]
            if result.detail:
                note_bits.append(result.detail)
            loc["notes"] = "; ".join(note_bits)
            entry["localization"] = loc
            if remaining is not None:
                remaining -= 1

        tickets.append(_coerce_ticket_entry(entry))

    by_outcome: dict[str, int] = {}
    for tr in tickets:
        by_outcome[tr["outcome"]] = by_outcome.get(tr["outcome"], 0) + 1

    report = {
        "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
        "productLine": defect_batch.productLine,
        "workDir": work_dir,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "openMr": open_mr,
        "mrUrl": None,
        "integrateMode": "single_mr" if open_mr else "none",
        "summary": {"total": len(tickets), "byOutcome": by_outcome},
        "tickets": tickets,
    }
    return validate_analysis_report(report)


def _coerce_ticket_entry(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        return TicketReport.model_validate(entry).model_dump()
    except Exception as err:  # noqa: BLE001
        return {
            "defectId": entry.get("defectId") or "unknown",
            "ticket": entry.get("ticket") or {},
            "localization": entry.get("localization")
            or {"candidates": [], "notes": "ticket validation failed"},
            "rootCause": {
                "summary": "Agent-3 ticket payload failed schema validation",
                "ruledOut": [],
                "openQuestions": [str(err)],
            },
            "outcome": "other_blocked",
            "proposedFix": None,
            "patch": None,
            "blockers": {
                "kind": "other_blocked",
                "detail": f"invalid ticket report: {err}",
            },
            "suggestedVerify": {"steps": [], "executed": False},
            "confidence": "low",
            "verifyStatus": "skipped",
        }


def _limit_from_env() -> Optional[int]:
    import os

    raw = os.environ.get("BUGFIX_ANALYZE_LIMIT")
    if raw is None or raw.strip() == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None
