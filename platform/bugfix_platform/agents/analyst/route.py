from __future__ import annotations

from typing import Any, Optional

from bugfix_contracts.code_knowledge import DefectCodeMatch
from bugfix_contracts.defect_batch import BatchTicket


def slice_ticket(t: BatchTicket) -> dict[str, Any]:
    return {
        "title": t.title,
        "testModule": t.testModule,
        "titleTag": t.titleTag,
        "intent": t.intent,
        "pool": t.pool,
        "observed": t.observed,
        "expected": t.expected,
        "steps": t.steps,
        "status": t.status,
        "severity": t.severity,
        "reasonCode": t.reasonCode,
        "reasonDetail": t.reasonDetail,
    }


def _missing_from_ticket(t: BatchTicket) -> list[str]:
    missing: list[str] = []
    if not (t.steps or "").strip():
        missing.append("复现步骤")
    if not (t.expected or "").strip():
        missing.append("期望结果")
    if not (t.observed or "").strip():
        missing.append("实际结果")
    if t.expectQuality in ("absent", "ambiguous"):
        missing.append("可判定的期望描述")
    if t.reasonDetail:
        missing.append(f"筛因补充: {t.reasonDetail}")
    return missing or ["更完整的缺陷描述/附件"]


def _soft_start_confidence(match: Optional[DefectCodeMatch]) -> str:
    """Agent-2 soft-start 置信度进 Agent-3 路由时的降权。

    纯 ``heuristic`` 候选只是路径 token 命中，不能当 medium/high 起点（否则
    analyze 会钉在错文件上）。有 grep/codegraph/claude_md 时仍封顶 medium。
    """
    if match is None or not match.candidates:
        return "low"
    sources = {str(c.source or "") for c in match.candidates}
    if sources and sources <= {"heuristic"}:
        return "low"
    conf = str(match.confidence or "low")
    if conf == "high":
        return "medium"
    return conf if conf in ("high", "medium", "low") else "low"


def route_ticket(ticket: BatchTicket, match: Optional[DefectCodeMatch]) -> dict[str, Any]:
    candidates = [
        {
            "repoPath": c.repoPath,
            "path": c.path,
            "symbol": c.symbol,
            "why": c.why,
            "source": c.source,
        }
        for c in (match.candidates if match else [])
    ]
    soft_conf = _soft_start_confidence(match)
    heuristic_only = bool(candidates) and {
        str(c.get("source") or "") for c in candidates
    } <= {"heuristic"}

    if ticket.pool == "needs_info":
        missing = _missing_from_ticket(ticket)
        return {
            "outcome": "needs_ticket_info",
            "proposedFix": None,
            "patch": None,
            "blockers": {
                "kind": "needs_ticket_info",
                "detail": ticket.reasonDetail or "screen funnel marked needs_info",
                "missingInfo": missing,
            },
            "rootCause": {
                "summary": "Insufficient ticket information to localize or propose a reliable fix",
                "ruledOut": [],
                "openQuestions": missing,
            },
            "localization": {
                "candidates": candidates,
                "notes": "soft-start matches retained; analysis blocked on ticket info",
            },
            "suggestedVerify": {"steps": ["补充缺陷单信息后重跑 Agent-3"], "executed": False},
            "confidence": "low",
            "verifyStatus": "skipped",
        }

    if not candidates:
        return {
            "outcome": "unlocalized",
            "proposedFix": None,
            "patch": None,
            "blockers": {
                "kind": "unlocalized",
                "detail": "no code candidates from Agent-2 soft-start",
            },
            "rootCause": {
                "summary": "Unable to localize to code with current code-knowledge matches",
                "ruledOut": [],
                "openQuestions": ["需要 CodeGraph/二次检索", "确认测试模块与代码目录映射"],
            },
            "localization": {
                "candidates": [],
                "notes": (
                    "empty defectCodeMatches.candidates"
                    + (f"; gap={match.gap}" if match and match.gap else "")
                ),
                "degradedSearch": False,
            },
            "suggestedVerify": {"steps": [], "executed": False},
            "confidence": "low",
            "verifyStatus": "skipped",
        }

    targets = [
        c["path"] if c["repoPath"] == "." else f'{c["repoPath"]}/{c["path"]}' for c in candidates
    ]
    notes = "consumed Agent-2 defectCodeMatches as soft start (D4)"
    if heuristic_only:
        notes += "; heuristic-only soft-start demoted to low — re-verify before trusting paths"
    return {
        "outcome": "plan_only",
        "proposedFix": {
            "summary": f"Inspect and fix around soft-matched paths for: {ticket.title[:80]}",
            "steps": [
                "Review soft-start candidates from code-knowledge"
                + (" (heuristic-only — re-search if doubtful)" if heuristic_only else ""),
                "Confirm root cause",
                "Apply minimal-diff patch under scope lock",
            ],
            "targetFiles": targets[:5],
        },
        "patch": None,
        "blockers": None,
        "rootCause": {
            "summary": "Localization soft-start available; root cause pending analyze session",
            "ruledOut": [],
            "openQuestions": ["根因待 analyze 会话确认"],
        },
        "localization": {
            "candidates": candidates,
            "notes": notes,
        },
        "suggestedVerify": {
            "steps": ["按业务模块手测复现步骤", "关注 candidate 文件相关单测（若有）"],
            "executed": False,
        },
        "confidence": soft_conf,
        "verifyStatus": "skipped",
    }
