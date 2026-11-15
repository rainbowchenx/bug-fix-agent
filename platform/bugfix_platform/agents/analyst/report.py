"""从已校验记录渲染可读报告。模型不得单独编造计数。"""

from __future__ import annotations

from typing import Any


def render_report(report: dict[str, Any]) -> str:
    tickets = list(report.get("tickets") or [])
    batch_id = report.get("batchId") or ""
    lines = [
        f"# Repair report {batch_id}".strip(),
        "",
        f"tickets: {len(tickets)}",
        "",
    ]
    for item in tickets:
        did = item.get("defectId") or ""
        resolution = item.get("resolution") or item.get("outcome") or ""
        lines.append(f"- {did}: {resolution}")
    return "\n".join(lines).strip() + "\n"
