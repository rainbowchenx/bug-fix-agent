from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from bugfix_agent.contracts.defect_batch import BatchTicket
from bugfix_agent.sdk.parse import parse_json_payload
from bugfix_agent.sdk.skills import skills_system_addon

AnalyzeMode = Literal["heuristic", "sdk"]

ANALYZE_TOOLS = ["Read", "Glob", "Grep"]
DISALLOWED_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit", "MultiEdit"]


@dataclass
class AnalyzeRequest:
    work_dir: str
    ticket: BatchTicket
    routed: dict[str, Any]
    """Pre-router outcome payload (soft-start localization, etc.)."""
    max_turns: int = 12
    model: Optional[str] = None


@dataclass
class AnalyzeResult:
    ok: bool
    payload: dict[str, Any]
    """Fields to merge onto the ticket report (outcome/rootCause/…)."""
    source: Literal["heuristic", "sdk", "sdk_fallback"]
    detail: Optional[str] = None


AnalyzeRunner = Callable[[AnalyzeRequest], AnalyzeResult]


def analyze_mode_from_env(explicit: Optional[str] = None) -> AnalyzeMode:
    raw = (explicit or os.environ.get("BUGFIX_ANALYZE_MODE") or "").strip().lower()
    if raw in ("sdk", "heuristic"):
        return raw  # type: ignore[return-value]
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sdk"
    return "heuristic"


def create_analyze_runner(mode: Optional[AnalyzeMode] = None) -> AnalyzeRunner:
    resolved = mode or analyze_mode_from_env()
    if resolved == "sdk":
        return run_claude_analyze
    return heuristic_analyze


def heuristic_analyze(req: AnalyzeRequest) -> AnalyzeResult:
    """No LLM: keep router payload; annotate that analyze session was skipped."""
    routed = dict(req.routed)
    root = dict(routed.get("rootCause") or {})
    notes = list(root.get("openQuestions") or [])
    if "analyze session skipped (heuristic mode)" not in notes:
        notes.append("analyze session skipped (heuristic mode)")
    root["openQuestions"] = notes
    routed["rootCause"] = root
    return AnalyzeResult(ok=True, payload=routed, source="heuristic")


def run_claude_analyze(req: AnalyzeRequest) -> AnalyzeResult:
    """Read-only Claude Agent SDK session → structured ticket analysis fields."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        fallback = heuristic_analyze(req)
        fallback.source = "sdk_fallback"
        fallback.detail = "ANTHROPIC_API_KEY missing; fell back to heuristic"
        return fallback

    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        fallback = heuristic_analyze(req)
        fallback.source = "sdk_fallback"
        fallback.detail = f"claude-agent-sdk not installed ({err}); fell back to heuristic"
        return fallback

    prompt = _build_prompt(req)
    model = req.model or os.environ.get("ANTHROPIC_MODEL") or None
    system_prompt = _SYSTEM_PROMPT + skills_system_addon(
        (
            "hierarchical-localization",
            "systematic-debugging",
            "test-triage",
            "typescript-null-safety",
            "vue-debug",
            "electron-process-boundary",
            "monorepo-workspace",
        )
    )
    options = ClaudeAgentOptions(
        cwd=req.work_dir,
        system_prompt=system_prompt,
        allowed_tools=list(ANALYZE_TOOLS),
        disallowed_tools=list(DISALLOWED_TOOLS),
        permission_mode="dontAsk",
        max_turns=req.max_turns,
        model=model,
    )

    result_text = ""
    structured: Any = None

    async def _run() -> None:
        nonlocal result_text, structured
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    raise RuntimeError(
                        "; ".join(message.errors or []) or message.result or "analyze SDK error"
                    )
                result_text = message.result or ""
                structured = message.structured_output

    try:
        anyio.run(_run)
    except Exception as err:  # noqa: BLE001
        fallback = heuristic_analyze(req)
        fallback.source = "sdk_fallback"
        fallback.detail = f"sdk analyze failed: {err}"
        return fallback

    parsed = parse_analyze_payload(structured if structured is not None else result_text)
    if parsed is None:
        fallback = heuristic_analyze(req)
        fallback.source = "sdk_fallback"
        fallback.detail = "sdk returned no parseable JSON analysis"
        return fallback

    merged = _merge_with_routed(req.routed, parsed)
    return AnalyzeResult(ok=True, payload=merged, source="sdk")


def parse_analyze_payload(raw: Any) -> Optional[dict[str, Any]]:
    parsed = parse_json_payload(raw)
    if parsed is None:
        return None
    return _normalize_payload(parsed)


def _normalize_payload(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "outcome" in data and isinstance(data["outcome"], str):
        out["outcome"] = data["outcome"]
    if isinstance(data.get("rootCause"), dict):
        out["rootCause"] = data["rootCause"]
    if isinstance(data.get("proposedFix"), dict):
        out["proposedFix"] = data["proposedFix"]
    if isinstance(data.get("localization"), dict):
        out["localization"] = data["localization"]
    if isinstance(data.get("blockers"), dict) or data.get("blockers") is None:
        if "blockers" in data:
            out["blockers"] = data["blockers"]
    if data.get("confidence") in ("high", "medium", "low"):
        out["confidence"] = data["confidence"]
    if isinstance(data.get("suggestedVerify"), dict):
        out["suggestedVerify"] = data["suggestedVerify"]
    return out


def _merge_with_routed(routed: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(routed)
    merged.update(parsed)
    # Preserve soft-start candidates if model omitted localization.
    if "localization" not in parsed and routed.get("localization"):
        merged["localization"] = routed["localization"]
    outcome = merged.get("outcome") or routed.get("outcome")
    merged["outcome"] = outcome
    actionable = outcome in ("patch_ready", "plan_only")
    if actionable:
        pf = merged.get("proposedFix") or routed.get("proposedFix")
        if not pf or not (pf.get("summary") if isinstance(pf, dict) else None):
            merged["proposedFix"] = routed.get("proposedFix") or {
                "summary": "See rootCause; propose minimal fix after confirming localization",
                "steps": [],
                "targetFiles": [],
            }
        merged["blockers"] = None
    else:
        if not merged.get("blockers"):
            merged["blockers"] = routed.get("blockers") or {
                "kind": outcome or "other_blocked",
                "detail": (merged.get("rootCause") or {}).get("summary") or "blocked by analyze",
            }
        # plan fields optional on blocked outcomes
    merged.setdefault("verifyStatus", "skipped")
    return merged


_SYSTEM_PROMPT = """You are Agent-3 defect analyst for a report-only workflow.
Use only Read / Glob / Grep. Do NOT edit files or run shell.
Ground claims in code you actually read. Prefer Agent-2 soft-start paths first.
End with a single JSON object (optionally in a ```json fence) with keys:
outcome, rootCause{summary,ruledOut,openQuestions}, proposedFix{summary,steps,targetFiles},
localization{candidates,notes}, blockers, confidence, suggestedVerify{steps,executed}.
outcome must be one of:
patch_ready, plan_only, needs_test_env, needs_ticket_info, needs_design_input,
not_code, config_or_dependency, unlocalized, other_blocked.
For this phase prefer plan_only when you have a credible root cause + fix plan but no patch file.
Set verifyStatus conceptually as skipped; suggestedVerify.executed must be false.
"""


def _build_prompt(req: AnalyzeRequest) -> str:
    t = req.ticket
    soft = req.routed.get("localization") or {}
    return (
        "Analyze this defect and return the JSON object described in the system prompt.\n\n"
        f"defectId: {t.defectId}\n"
        f"title: {t.title}\n"
        f"pool: {t.pool}\n"
        f"testModule: {t.testModule}\n"
        f"titleTag: {t.titleTag}\n"
        f"intent: {t.intent}\n"
        f"observed: {t.observed}\n"
        f"expected: {t.expected}\n"
        f"steps: {t.steps}\n"
        f"expectQuality: {t.expectQuality}\n"
        f"softStartLocalization: {json.dumps(soft, ensure_ascii=False)}\n"
        f"routerOutcomeHint: {req.routed.get('outcome')}\n"
    )
