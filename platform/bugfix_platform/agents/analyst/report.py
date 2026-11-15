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
        cause = ""
        root = item.get("rootCause")
        if isinstance(root, dict):
            cause = str(root.get("summary") or "")
        if cause:
            lines.append(f"  cause: {cause}")
        patch = item.get("patch") if isinstance(item.get("patch"), dict) else {}
        patch_path = (patch or {}).get("path")
        if patch_path:
            lines.append(f"  patch: {patch_path}")
        blockers = item.get("blockers") if isinstance(item.get("blockers"), dict) else {}
        detail = (blockers or {}).get("detail")
        if detail:
            lines.append(f"  blocked: {detail}")
        missing = (blockers or {}).get("missingInfo") or []
        if missing:
            lines.append(f"  need: {', '.join(str(x) for x in missing)}")
    return "\n".join(lines).strip() + "\n"
