"""从已校验记录渲染可读报告。模型不得单独编造计数。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bugfix_contracts.analysis_report import AnalysisReport


def render_analysis_markdown(report: AnalysisReport) -> str:
    return render_report({"batchId": report.productLine, "tickets": report.model_dump()["tickets"]})


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
        lines.append(f"  analysis: {item.get('analysisStatus', 'not_executed')}; actionability: {item.get('actionability') or {}}")
        if usage := item.get("analysisUsage"):
            lines.append(
                f"  analysisUsage: turns={usage['turns']} ({usage['turnReports']}/{usage['sdkCalls']} SDK calls); "
                f"tokens in={usage['inputTokens']} out={usage['outputTokens']} "
                f"cache_read={usage['cacheReadTokens']} cache_write={usage['cacheWriteTokens']} "
                f"({usage['usageReports']}/{usage['sdkCalls']} SDK calls); "
                f"Read requests={usage['readRequests']} blocked={usage['readBlocked']} executed={usage['readCalls']} "
                f"lines={usage['readResultLines']} bytes={usage['readResultBytes']}"
            )
            for name, key in (("CodeGraph", "codeGraph"), ("Grep/Glob", "grepGlob")):
                lines.append(
                    f"  {name} requests={usage[key + 'Requests']} blocked={usage[key + 'Blocked']} "
                    f"executed={usage[key + 'Calls']}"
                )
        attempt_id = item.get("attemptId") or ""
        if attempt_id:
            lines.append(f"  feedbackForm: defects/{did}/attempts/{attempt_id}/feedback-form.md")
        target=(item.get('ticket') or {}).get('expected')
        if target:
            lines.append(f"  currentTarget: {target}")
        for attachment in item.get('attachments') or []:
            lines.append(f"  attachment: {attachment.get('ref')} available={attachment.get('availability')} read={attachment.get('read')}")
        for candidate in (item.get("localization") or {}).get("candidates") or []:
            path = candidate.get("path", "")
            repo = candidate.get("repoPath")
            location = f"{repo}/{path}" if repo and repo != "." else path
            symbol = candidate.get("symbol")
            lines.append(f"  location: {location}" + (f" ({symbol})" if symbol else ""))
        cause = ""
        root = item.get("rootCause")
        if isinstance(root, dict):
            cause = str(root.get("summary") or "")
        if cause:
            lines.append(f"  cause: {cause}")
        for claim in (root or {}).get("claims") or []:
            lines.append(f"  claim [{claim.get('status')}]: {claim.get('statement')}")
        for question in (root or {}).get("questions") or []:
            lines.append(f"  question [{question.get('kind')}]: {question.get('reason')}; need {question.get('requestedEvidence', '')}")
        proposal = item.get("proposedFix") or {}
        if proposal.get("summary"):
            lines.append(f"  proposedFix: {proposal['summary']}")
        for step in proposal.get("steps") or []:
            lines.append(f"    - {step}")
        if proposal.get("targetFiles"):
            lines.append(f"  targetFiles: {', '.join(proposal['targetFiles'])}")
        patch = item.get("patch") if isinstance(item.get("patch"), dict) else {}
        patch_path = (patch or {}).get("path")
        if patch_path:
            lines.append(f"  patch: {patch_path}")
        commit_message = patch.get("commitMessage")
        if commit_message:
            lines.append("  commitMessage:")
            lines.extend(f"    {line}" for line in commit_message.splitlines())
        summary = (patch or {}).get("summary") or ""
        if summary:
            lines.append(f"  patchFiles: {summary}")
        blockers = item.get("blockers") if isinstance(item.get("blockers"), dict) else {}
        detail = (blockers or {}).get("detail")
        if detail:
            lines.append(f"  blocked: {detail}")
        missing = (blockers or {}).get("missingInfo") or []
        if missing:
            lines.append(f"  need: {', '.join(str(x) for x in missing)}")
        verify = item.get("suggestedVerify") if isinstance(item.get("suggestedVerify"), dict) else {}
        for cmd in (verify or {}).get("commands") or []:
            if not isinstance(cmd, dict):
                continue
            result = str(cmd.get("result") or "")
            coverage = str(cmd.get("coverage") or "")
            argv = " ".join(str(x) for x in (cmd.get("command") or [])[:6])
            lines.append(f"  check: {result} {coverage} {argv}".strip())
            log_ref = cmd.get("logRef")
            if log_ref:
                lines.append(f"  log: {log_ref}")
                excerpt = _log_excerpt(str(log_ref))
                if excerpt:
                    lines.append(f"  logExcerpt: {excerpt}")
        for step in (verify or {}).get("steps") or []:
            lines.append(f"  remaining: {step}")
    return "\n".join(lines).strip() + "\n"


def _log_excerpt(ref: str) -> str:
    path = Path(ref)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text:
        return ""
    return text.splitlines()[0][:200]
