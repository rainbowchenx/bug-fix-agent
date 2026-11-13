"""Agent-3 只读 analyze：Claude Agent SDK 会话 → 单票报告字段。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.sdk.parse import parse_json_payload
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS, CodeGraphStatus
from bugfix_platform.sdk.skill_inject import InjectedSkill, analyze_skills_addon
from bugfix_platform.sdk.skills import skills_system_addon

AnalyzeMode = Literal["heuristic", "sdk"]

ANALYZE_TOOLS = ["Read", "Glob", "Grep"]
DISALLOWED_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit", "MultiEdit"]
_CATALOG_ROLES = frozenset({"shell", "host", "route_table"})
_BUDGET_SUBTYPES = frozenset({"error_max_turns", "error_max_budget_usd"})
_SALVAGE_PROMPT = (
    "Stop exploring. Return the JSON analysis object now. Incomplete is OK. "
    "Do not edit files."
)
DEFAULT_ANALYZE_MAX_TURNS = 24


@dataclass
class AnalyzeRequest:
    work_dir: str
    ticket: BatchTicket
    routed: dict[str, Any]
    max_turns: int = DEFAULT_ANALYZE_MAX_TURNS
    model: Optional[str] = None
    injected_skills: tuple[InjectedSkill, ...] = ()
    cartography_profile: str = "unknown"
    architecture: Optional[dict[str, Any]] = None
    reading_playbook: str = ""
    apply_fix: bool = False
    spec_atlas: Optional[dict[str, Any]] = None
    codegraph: Optional[CodeGraphStatus] = None


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
    if has_credentials():
        return "sdk"
    return "heuristic"


def resolve_analyze_max_turns(explicit: Optional[int] = None) -> int:
    """Return SDK ``max_turns`` (default 24)."""
    if explicit is not None:
        return max(1, int(explicit))
    raw = (os.environ.get("BUGFIX_ANALYZE_MAX_TURNS") or "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_ANALYZE_MAX_TURNS


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


def _blocked_analyze(req: AnalyzeRequest, detail: str) -> AnalyzeResult:
    """Honest failure: do not copy a router plan_only as if analysis ran."""
    routed = dict(req.routed)
    loc = dict(routed.get("localization") or {})
    return AnalyzeResult(
        ok=True,
        source="sdk_fallback",
        detail=detail,
        payload={
            **routed,
            "outcome": "other_blocked",
            "proposedFix": None,
            "patch": None,
            "blockers": {"kind": "other_blocked", "detail": detail},
            "rootCause": {
                "summary": "Analyze session did not complete",
                "ruledOut": [],
                "openQuestions": [detail],
            },
            "localization": loc,
            "confidence": "low",
            "verifyStatus": "skipped",
            "suggestedVerify": routed.get("suggestedVerify")
            or {"steps": [], "executed": False},
        },
    )


def run_claude_analyze(req: AnalyzeRequest) -> AnalyzeResult:
    """Read-only Claude Agent SDK session → structured ticket analysis fields."""
    if not has_credentials():
        return _blocked_analyze(
            req,
            "no Anthropic credentials in env (ANTHROPIC_API_KEY / "
            "ANTHROPIC_AUTH_TOKEN)",
        )

    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        return _blocked_analyze(req, f"claude-agent-sdk not installed ({err})")

    prompt = _build_prompt(req)
    model = req.model or os.environ.get("ANTHROPIC_MODEL") or None
    if req.injected_skills:
        system_prompt = _SYSTEM_PROMPT + analyze_skills_addon(req.injected_skills)
    else:
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
    max_turns = resolve_analyze_max_turns(req.max_turns)

    def _make_options(*, resume: str | None = None, turns: Optional[int] = None) -> Any:
        kwargs: dict[str, Any] = {
            "cwd": req.work_dir,
            "system_prompt": system_prompt,
            "allowed_tools": analyze_allowed_tools(req.codegraph),
            "disallowed_tools": list(DISALLOWED_TOOLS),
            "permission_mode": "dontAsk",
            "max_turns": turns if turns is not None else max_turns,
            "model": model,
        }
        if req.codegraph is not None:
            kwargs.update(req.codegraph.mcp_option_kwargs(req.work_dir))
        if resume:
            kwargs["resume"] = resume
        try:
            return ClaudeAgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("resume", None)
            kwargs.pop("strict_mcp_config", None)
            try:
                return ClaudeAgentOptions(**kwargs)
            except TypeError:
                kwargs.pop("mcp_servers", None)
                return ClaudeAgentOptions(**kwargs)

    texts: list[str] = []
    result_text = ""
    structured: Any = None
    session_id: str | None = None
    budget_stop = False

    async def _drive(prompt_text: str, opts: Any) -> None:
        nonlocal result_text, structured, session_id, budget_stop
        async for message in query(prompt=prompt_text, options=opts):
            text = _message_text(message)
            if text.strip():
                texts.append(text)
            if not isinstance(message, ResultMessage):
                continue
            session_id = getattr(message, "session_id", None) or session_id
            structured = message.structured_output
            result_text = message.result or ""
            if _budget_exhausted(message):
                budget_stop = True
                continue
            if message.is_error:
                raise RuntimeError(
                    "; ".join(message.errors or []) or message.result or "analyze SDK error"
                )

    try:
        anyio.run(_drive, prompt, _make_options())
    except Exception as err:  # noqa: BLE001
        if not budget_stop:
            return _blocked_analyze(req, f"sdk analyze failed: {err}")

    parsed = _parse_session_json(structured, texts + [result_text])
    if parsed is None and budget_stop and session_id:
        salvage_texts: list[str] = []

        async def _salvage() -> None:
            nonlocal structured, result_text
            async for message in query(
                prompt=_SALVAGE_PROMPT,
                options=_make_options(resume=session_id, turns=2),
            ):
                text = _message_text(message)
                if text.strip():
                    salvage_texts.append(text)
                if not isinstance(message, ResultMessage):
                    continue
                structured = message.structured_output
                result_text = message.result or ""
                if message.is_error and not _budget_exhausted(message):
                    raise RuntimeError(
                        "; ".join(message.errors or [])
                        or message.result
                        or "analyze salvage error"
                    )

        try:
            anyio.run(_salvage)
        except Exception:  # noqa: BLE001
            pass
        parsed = _parse_session_json(structured, texts + salvage_texts + [result_text])

    if parsed is None:
        return _blocked_analyze(req, "sdk returned no parseable JSON analysis")

    merged = _merge_with_routed(
        req.routed,
        parsed,
        work_dir=req.work_dir,
        architecture=req.architecture,
        apply_fix=req.apply_fix,
    )
    detail = "partial=true; reason=max_turns" if budget_stop else None
    return AnalyzeResult(ok=True, payload=merged, source="sdk", detail=detail)


def parse_analyze_payload(raw: Any) -> Optional[dict[str, Any]]:
    parsed = parse_json_payload(raw)
    if parsed is None:
        return None
    return _normalize_payload(parsed)


def _parse_session_json(structured: Any, texts: list[str]) -> Optional[dict[str, Any]]:
    parsed = parse_analyze_payload(structured)
    if parsed is not None:
        return parsed
    for text in reversed(texts):
        parsed = parse_analyze_payload(text)
        if parsed is not None:
            return parsed
    return None


def _message_text(message: Any) -> str:
    result = getattr(message, "result", None)
    if isinstance(result, str) and result.strip():
        return result
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    bits: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            bits.append(text)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            bits.append(block["text"])
    return "\n".join(bits)


def _budget_exhausted(message: Any) -> bool:
    subtype = str(getattr(message, "subtype", "") or "")
    terminal = str(getattr(message, "terminal_reason", "") or "")
    return subtype in _BUDGET_SUBTYPES or terminal in {"max_turns", "max_budget_usd"}


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
    if isinstance(data.get("patch"), dict) or data.get("patch") is None:
        if "patch" in data:
            out["patch"] = data["patch"]
    return out


def _norm_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def _work_rel(candidate: dict[str, Any]) -> str:
    repo = candidate.get("repoPath") or "."
    path = _norm_path(str(candidate.get("path") or ""))
    if repo in (".", ""):
        return path
    return f"{_norm_path(str(repo))}/{path}" if path else _norm_path(str(repo))


def _is_catalog_path(rel: str, architecture: Optional[dict[str, Any]]) -> bool:
    if not architecture:
        return False
    path = _norm_path(rel)
    for mod in architecture.get("modules") or []:
        if not isinstance(mod, dict):
            continue
        if (mod.get("role") or "") not in _CATALOG_ROLES:
            continue
        if _norm_path(str(mod.get("path") or "")) == path:
            return True
    return False


def _candidate_exists(work_dir: str, candidate: dict[str, Any]) -> bool:
    repo = candidate.get("repoPath") or "."
    rel = Path(str(candidate.get("path") or ""))
    root = Path(work_dir)
    abs_path = root / repo / rel if repo not in (".", "") else root / rel
    try:
        return abs_path.resolve().is_file()
    except OSError:
        return False


def _sanitize_candidates(
    work_dir: Optional[str],
    candidates: list[Any],
    architecture: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    if not work_dir:
        return [c for c in candidates if isinstance(c, dict) and c.get("path")]
    for cand in candidates:
        if not isinstance(cand, dict) or not cand.get("path"):
            continue
        rel = _work_rel(cand)
        if _is_catalog_path(rel, architecture):
            continue
        if not _candidate_exists(work_dir, cand):
            continue
        kept.append(cand)
    return kept


def _merge_with_routed(
    routed: dict[str, Any],
    parsed: dict[str, Any],
    *,
    work_dir: Optional[str] = None,
    architecture: Optional[dict[str, Any]] = None,
    apply_fix: bool = False,
) -> dict[str, Any]:
    merged = dict(routed)
    merged.update(parsed)
    if "localization" not in parsed and routed.get("localization"):
        merged["localization"] = routed["localization"]
    loc = dict(merged.get("localization") or {})
    raw_cands = loc.get("candidates") or []
    if isinstance(raw_cands, list):
        kept = _sanitize_candidates(work_dir, raw_cands, architecture)
        if work_dir and len(kept) < len([c for c in raw_cands if isinstance(c, dict)]):
            loc["notes"] = "; ".join(
                x for x in [loc.get("notes"), "dropped missing/catalog loci"] if x
            )
        loc["candidates"] = kept
        if not kept and raw_cands:
            loc["degradedSearch"] = True
        merged["localization"] = loc
        if work_dir and not kept and merged.get("outcome") in ("plan_only", "patch_ready"):
            merged["outcome"] = "unlocalized"
            merged["proposedFix"] = None
            merged["patch"] = None
            merged["blockers"] = {
                "kind": "unlocalized",
                "detail": "analyze named no existing non-catalog paths",
            }
    outcome = merged.get("outcome") or routed.get("outcome")
    if not apply_fix and outcome == "patch_ready":
        outcome = "plan_only"
        merged["patch"] = None
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
    merged.setdefault("verifyStatus", "skipped")
    return merged


_SYSTEM_PROMPT = """You are Agent-3 defect analyst.
Tools: Read, Glob, Grep, and CodeGraph MCP when mounted. Do NOT edit files or run shell.
When CodeGraph is ready (codegraph_explore / codegraph_node / callers / callees),
the first symbol or call-flow tool call MUST be codegraph_explore (or callers/callees).
Treat CodeGraph excerpts as already Read; do not re-Grep symbols it returned.
Fall back to Grep/Read/Glob only when CodeGraph is unavailable or empty.
Ground claims in code you actually read.
Prefer Agent-2 architecture map and soft-start paths first, then follow imports/callers
from those paths to name the likely fix locus. Do not assume Agent-2 already found
the root cause. Heuristic-only soft-start paths are unverified token hits — confirm
with CodeGraph (or re-Grep) before trusting them; empty or weak matches mean you
may Glob/Grep yourself.
If ticketSpecDirs is non-empty, Read that directory's index/README (or one key md);
do not read the whole specAtlas tree.
Shell / host / route_table files are catalogs, not fix loci.
Repo-specific injected skills (if attached) have HIGHEST PRIORITY over package SOP:
follow their read order, test/dev conventions, module aliases, and product-line naming.
They do not let you invent paths or schema fields.
End with a single JSON object (optionally in a ```json fence) with keys:
outcome, rootCause{summary,ruledOut,openQuestions}, proposedFix{summary,steps,targetFiles},
localization{candidates,notes}, blockers, confidence, suggestedVerify{steps,executed}.
outcome must be one of:
patch_ready, plan_only, needs_test_env, needs_ticket_info, needs_design_input,
not_code, config_or_dependency, unlocalized, other_blocked.
When applyFix is false, never claim patch_ready — use plan_only when you have a
credible root cause and fix plan. Do not invent a patch file.
Set verifyStatus conceptually as skipped; suggestedVerify.executed must be false.
"""


def analyze_allowed_tools(codegraph: Optional[CodeGraphStatus] = None) -> list[str]:
    """Always Read/Glob/Grep; append CodeGraph MCP names only when the index is ready."""
    tools = list(ANALYZE_TOOLS)
    if codegraph is not None and codegraph.ready:
        tools.extend(CODEGRAPH_MCP_TOOLS)
    return tools


def select_ticket_spec_dirs(
    spec_atlas: Optional[dict[str, Any]],
    architecture: Optional[dict[str, Any]],
    routed: dict[str, Any],
    *,
    limit: int = 2,
) -> list[str]:
    """Pick up to ``limit`` spec dirs matching this ticket's soft-start paths.

    Empty is valid: no candidates, or no ``doc_ref`` that shares a module id.
    """
    refs: list[str] = []
    for entry in list((spec_atlas or {}).get("entries") or []):
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") != "doc_ref" or not entry.get("path"):
            continue
        refs.append(str(entry["path"]).replace("\\", "/").rstrip("/"))
    if not refs:
        return []
    loc = routed.get("localization") or {}
    cands = list(loc.get("candidates") or []) if isinstance(loc, dict) else []
    modules = list((architecture or {}).get("modules") or [])
    hit_ids: list[str] = []
    for cand in cands:
        if not isinstance(cand, dict):
            continue
        path = str(cand.get("path") or "").replace("\\", "/")
        repo = str(cand.get("repoPath") or "")
        full = f"{repo}/{path}" if repo not in (".", "") else path
        blob = f"/{full.strip('/')}/"
        for mod in modules:
            if not isinstance(mod, dict):
                continue
            mid = str(mod.get("id") or "").strip()
            mpath = str(mod.get("path") or "").replace("\\", "/").rstrip("/")
            if mid and f"/{mid}/" in blob:
                hit_ids.append(mid)
            elif mid and mpath and (full.startswith(mpath) or path.startswith(mpath)):
                hit_ids.append(mid)
    out: list[str] = []
    seen: set[str] = set()
    for mid in dict.fromkeys(hit_ids):
        for ref in refs:
            if f"/{mid}/" in f"/{ref}/" and ref not in seen:
                seen.add(ref)
                out.append(ref)
                if len(out) >= limit:
                    return out
    return out


def _build_prompt(req: AnalyzeRequest) -> str:
    t = req.ticket
    soft = req.routed.get("localization") or {}
    apply_flag = "true" if req.apply_fix else "false"
    cg = req.codegraph
    cg_line = (
        cg.prompt_roots_line()
        if cg is not None
        else "codeGraph: unavailable — use Grep/Read/Glob only"
    )
    ticket_specs = select_ticket_spec_dirs(req.spec_atlas, req.architecture, req.routed)
    return (
        "Analyze this defect and return the JSON object described in the system prompt.\n\n"
        f"defectId: {t.defectId}\n"
        f"title: {t.title}\n"
        f"pool: {t.pool}\n"
        f"testModule: {t.testModule}\n"
        f"titleTag: {t.titleTag}\n"
        f"intent: {t.intent}\n"
        f"intentRationale: {(t.intentRationale or '')[:400]}\n"
        f"observed: {t.observed}\n"
        f"expected: {t.expected}\n"
        f"steps: {t.steps}\n"
        f"expectQuality: {t.expectQuality}\n"
        f"injectedSkills: {json.dumps([s.name for s in req.injected_skills], ensure_ascii=False)}\n"
        f"cartographyProfile: {req.cartography_profile}\n"
        f"readingPlaybook: {req.reading_playbook}\n"
        f"architectureMap: {json.dumps(req.architecture or {}, ensure_ascii=False)}\n"
        f"specAtlas: {json.dumps(req.spec_atlas or {}, ensure_ascii=False)}\n"
        f"ticketSpecDirs: {json.dumps(ticket_specs, ensure_ascii=False)}\n"
        f"{cg_line}\n"
        f"softStartLocalization: {json.dumps(soft, ensure_ascii=False)}\n"
        f"matchGap: {(soft.get('notes') if isinstance(soft, dict) else '') or ''}\n"
        f"routerOutcomeHint: {req.routed.get('outcome')}\n"
        f"applyFix: {apply_flag}\n"
    )
