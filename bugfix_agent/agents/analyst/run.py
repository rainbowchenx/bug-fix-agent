from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bugfix_agent.agents.analyst.route import route_ticket, slice_ticket
from bugfix_agent.contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_analysis_report,
)


def run_analyst(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    code_knowledge: CodeKnowledge,
    open_mr: bool = False,
) -> AnalysisReport:
    work_dir = str(work_dir)
    match_by_id = {m.defectId: m for m in code_knowledge.defectCodeMatches}

    tickets = []
    for t in defect_batch.tickets:
        if not is_match_pool(t.pool):
            continue
        routed = route_ticket(t, match_by_id.get(t.defectId))
        tickets.append(
            {
                "defectId": t.defectId,
                "ticket": slice_ticket(t),
                **routed,
            }
        )

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
