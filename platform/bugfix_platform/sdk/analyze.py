"""Agent-3 只读 analyze：Claude Agent SDK 会话 → 单票报告字段。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.sdk.parse import budget_exhausted, message_text, parse_json_payload
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS, CodeGraphStatus
from bugfix_platform.sdk.model_env import model_from_env, sdk_options_env
from bugfix_platform.sdk.project_mcp import ProjectMcp
from bugfix_platform.sdk.skill_inject import InjectedSkill, analyze_skills_addon, repair_skill_addon
from bugfix_platform.sdk.skills import skills_system_addon
from bugfix_platform.sdk.trace import open_recorder

AnalyzeMode = Literal["heuristic", "sdk"]

ANALYZE_TOOLS = ["Read", "Glob", "Grep"]
DISALLOWED_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit", "MultiEdit"]
_CATALOG_ROLES = frozenset({"shell", "host", "route_table"})
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
    investigation: Optional[dict[str, Any]] = None
    resume_session_id: Optional[str] = None
    previous_attempt: Optional[dict[str, Any]] = None
    project_mcp: ProjectMcp = field(default_factory=ProjectMcp)
    repair_skill: InjectedSkill | None = None
    artifact_dir: Optional[str] = None
    """产物根；给了就往 ``<artifact_dir>/logs/`` 写 SDK 轨迹（见 :mod:`trace`）。"""


@dataclass
class AnalyzeResult:
    ok: bool
    payload: dict[str, Any]
    """Fields to merge onto the ticket report (outcome/rootCause/…)."""
    source: Literal["heuristic", "sdk", "sdk_fallback"]
    detail: Optional[str] = None
    session_id: Optional[str] = None
    skill_reads: list[str] = field(default_factory=list)
    read_paths: list[str] = field(default_factory=list)


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
            "no credentials in env (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN, "
            "or platform-injected OPENAI_API_KEY)",
        )

    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        return _blocked_analyze(req, f"claude-agent-sdk not installed ({err})")

    prompt = _build_prompt(req)
    model = model_from_env(req.model)
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
    system_prompt += repair_skill_addon(req.repair_skill)
    if req.project_mcp.full_access:
        system_prompt += "\nUse the available project MCP tools and Claude Code plugins when relevant. The analysis phase remains read-only for repository files."
    max_turns = resolve_analyze_max_turns(req.max_turns)

    option_notes: list[str] = []

    def _make_options(
        *,
        resume: str | None = None,
        turns: Optional[int] = None,
        allow_resume: bool = True,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "cwd": req.work_dir,
            "system_prompt": system_prompt,
            "allowed_tools": [*analyze_allowed_tools(req.codegraph), *req.project_mcp.allowed_tools()],
            "disallowed_tools": list(DISALLOWED_TOOLS),
            "permission_mode": "dontAsk",
            "max_turns": turns if turns is not None else max_turns,
            "model": model,
        }
        kwargs.update(req.project_mcp.sdk_options(req.work_dir, req.codegraph))
        kwargs.update(recorder.sdk_options(ClaudeAgentOptions))
        resume_id = resume if resume is not None else req.resume_session_id
        if resume_id and allow_resume:
            kwargs["resume"] = resume_id
        # 平台注入 OPENAI_*、SDK 只认 ANTHROPIC_*，在 spawn 时按次覆盖。
        # 同时补 cli_path（包里不带 356 MB 的 claude.exe）。
        kwargs = sdk_options_env(kwargs)
        try:
            return ClaudeAgentOptions(**kwargs)
        except TypeError:
            if "resume" not in kwargs:
                raise
            option_notes.append("resume unsupported, starting new session")
            kwargs.pop("resume", None)
            try:
                return ClaudeAgentOptions(**kwargs)
            except TypeError:
                # 老版本 SDK 不认 cli_path；去掉后走它自己的 CLI 查找。
                kwargs.pop("cli_path", None)
                return ClaudeAgentOptions(**kwargs)

    texts: list[str] = []
    result_text = ""
    structured: Any = None
    session_id: str | None = None
    budget_stop = False
    skill_reads: list[str] = []
    pending_skill_reads: dict[str, str] = {}
    read_paths: list[str] = []
    pending_reads: dict[str, str] = {}

    ticket_ids = [req.ticket.defectId]
    recorder = open_recorder(
        req.artifact_dir,
        f"agent3-{req.ticket.defectId}",
        tag="[agent3]",
    )

    def finish(result: AnalyzeResult) -> AnalyzeResult:
        result.skill_reads = list(dict.fromkeys(skill_reads))
        result.read_paths = list(dict.fromkeys(read_paths))
        recorder.close()
        return result

    def observe_reads(message: Any) -> None:
        for block in getattr(message, "content", []) or []:
            if getattr(block, "name", None) == "Read":
                params = getattr(block, "input", {}) or {}
                ref = params.get("file_path")
                if ref:
                    path = Path(ref)
                    if not path.is_absolute():
                        path = Path(req.work_dir) / path
                    resolved = str(path.resolve())
                    pending_reads[str(getattr(block, "id", ""))] = resolved
                    if any(resolved == str(s.skill_md.resolve()) for s in req.injected_skills):
                        pending_skill_reads[str(getattr(block, "id", ""))] = resolved
            use_id = str(getattr(block, "tool_use_id", ""))
            if use_id in pending_reads and not getattr(block, "is_error", False) and getattr(block, "content", None):
                read_paths.append(pending_reads.pop(use_id))
            if use_id in pending_skill_reads and not getattr(block, "is_error", False) and getattr(block, "content", None):
                skill_reads.append(pending_skill_reads.pop(use_id))

    async def _drive(prompt_text: str, opts: Any, phase: str = "analysis") -> None:
        nonlocal result_text, structured, session_id, budget_stop
        recorder.begin(phase, prompt_text, tickets=ticket_ids)
        terminal_error: str | None = None
        async for message in query(prompt=prompt_text, options=opts):
            recorder.message(message)
            observe_reads(message)
            text = message_text(message)
            if text.strip():
                texts.append(text)
            if not isinstance(message, ResultMessage):
                continue
            session_id = getattr(message, "session_id", None) or session_id
            structured = message.structured_output
            result_text = message.result or ""
            if budget_exhausted(message):
                budget_stop = True
                continue
            if message.is_error and terminal_error is None:
                terminal_error = "; ".join(message.errors or []) or message.result or "analyze SDK error"
        # Let the SDK close its transport on the same event loop before surfacing a result error.
        if terminal_error is not None:
            raise RuntimeError(terminal_error)

    try:
        anyio.run(_drive, prompt, _make_options())
    except Exception as err:  # noqa: BLE001
        recorder.error(err)
        from bugfix_platform.sdk.runtime_profile import modality_error
        if modality_error(str(err)):
            return finish(_blocked_analyze(req, "model modality configuration mismatch; image not analyzed; " + str(err)))
        if req.resume_session_id and not budget_stop:
            option_notes.append(f"session inaccessible: {err}; starting new session")
            try:
                anyio.run(_drive, prompt, _make_options(allow_resume=False), "analysis retry")
            except Exception as err2:  # noqa: BLE001
                recorder.error(err2)
                if not budget_stop:
                    return finish(_blocked_analyze(req, f"sdk analyze failed: {err2}"))
        elif not budget_stop:
            return finish(_blocked_analyze(req, f"sdk analyze failed: {err}"))

    reject_notes: list[str] = []
    parsed = _parse_session_json(structured, texts + [result_text], reject_notes)
    # salvage 不再只在 budget_stop 时触发：模型正常回合里输出一份「JSON 合法但
    # 不合契约」的分析（典型是 duplicate claimId）同样值得再问一次 —— 那是一次
    # 已经付过费的会话，直接判死太浪费。
    if parsed is None and session_id:
        salvage_texts: list[str] = []

        async def _salvage() -> None:
            nonlocal structured, result_text
            recorder.begin("analysis salvage", _SALVAGE_PROMPT, tickets=ticket_ids)
            terminal_error: str | None = None
            async for message in query(
                prompt=_SALVAGE_PROMPT,
                options=_make_options(resume=session_id, turns=2),
            ):
                recorder.message(message)
                observe_reads(message)
                text = message_text(message)
                if text.strip():
                    salvage_texts.append(text)
                if not isinstance(message, ResultMessage):
                    continue
                structured = message.structured_output
                result_text = message.result or ""
                if message.is_error and terminal_error is None and not budget_exhausted(message):
                    terminal_error = "; ".join(message.errors or []) or message.result or "analyze salvage error"
            if terminal_error is not None:
                raise RuntimeError(terminal_error)

        try:
            anyio.run(_salvage)
        except Exception as err:  # noqa: BLE001
            recorder.error(err)
        retry_notes: list[str] = []
        parsed = _parse_session_json(
            structured, texts + salvage_texts + [result_text], retry_notes
        )
        reject_notes = retry_notes or reject_notes
        if parsed is not None:
            # 首次输出违规、salvage 才拿到合规内容 —— 记下来，好统计这类频率。
            option_notes.append("salvaged after first response was unusable")

    if parsed is None:
        detail = "sdk returned no parseable JSON analysis"
        if reject_notes:
            # 说清楚到底是「没给 JSON」还是「给了但违反契约」。
            unique = list(dict.fromkeys(reject_notes))
            detail = "sdk analysis unusable: " + "; ".join(unique[:2])
        return finish(_blocked_analyze(req, detail))

    root_shape = (parsed or {}).get("rootCause") or {}
    if not isinstance(root_shape.get("questions"), list) or not isinstance(root_shape.get("claims"), list):
        option_notes.append("quality fields missing; bounded format repair")
        try:
            anyio.run(_drive,
                "Return the same analysis with rootCause.claims and rootCause.questions arrays. "
                "Do not invent certainty. Classify unresolved blockers and preserve user target. "
                + json.dumps(parsed, ensure_ascii=False),
                _make_options(resume=session_id, turns=2), "analysis format repair")
            parsed = _parse_session_json(structured, texts + [result_text])
        except Exception as err:
            recorder.error(err)
        root_shape = (parsed or {}).get("rootCause") or {}
        if not isinstance(root_shape.get("questions"), list) or not isinstance(root_shape.get("claims"), list):
            blocked = _blocked_analyze(req, "analysis incomplete: missing structured claims/questions after format repair")
            if parsed and isinstance(parsed.get("rootCause"), dict):
                partial_root=dict(parsed["rootCause"])
                partial_root["summary"]="[Incomplete] " + str(partial_root.get("summary") or "")
                partial_root["claims"]=partial_root.get("claims") or []
                partial_root["questions"]=(partial_root.get("questions") or []) + [{
                    "id":"analysis-incomplete", "kind":"blocking", "reason":"Structured analysis incomplete; retry required"}]
                from bugfix_contracts.analysis_report import normalize_root
                blocked.payload["rootCause"]=normalize_root(partial_root)
            return finish(blocked)

    merged = _merge_with_routed(
        req.routed,
        parsed,
        work_dir=req.work_dir,
        architecture=req.architecture,
        apply_fix=req.apply_fix,
    )
    detail_bits = []
    if budget_stop:
        detail_bits.append("partial=true; reason=max_turns")
    detail_bits.extend(option_notes)
    detail = "; ".join(detail_bits) or None
    return finish(AnalyzeResult(
        ok=True, payload=merged, source="sdk", detail=detail, session_id=session_id,
    ))


def parse_analyze_payload(raw: Any, notes: Optional[list[str]] = None) -> Optional[dict[str, Any]]:
    """解析一份模型输出；失败返回 ``None``，并把原因追加到 ``notes``。

    失败分两类，**必须区分开**，否则日志会误导：

    - ``不是 JSON``：模型根本没按格式输出
    - ``JSON 合法但不合契约``：``normalize_root()`` 抛的
      ``duplicate claimId`` / ``question references unknown claim`` /
      ``Claim`` 的 ValidationError

    第二类以前和第一类一样报 ``no parseable JSON``，实际是结构违规 ——
    查日志时会往"模型没输出 JSON"这个错误方向走。
    """
    parsed = parse_json_payload(raw)
    if parsed is None:
        return None
    try:
        return _normalize_payload(parsed)
    except (ValueError, TypeError) as err:
        if notes is not None:
            reason = f"{type(err).__name__}: {err}"
            # 一行就够，别把整份 payload 塞进诊断
            notes.append(f"parsed JSON rejected by contract ({reason.splitlines()[0][:160]})")
        return None


def _parse_session_json(
    structured: Any, texts: list[str], notes: Optional[list[str]] = None
) -> Optional[dict[str, Any]]:
    parsed = parse_analyze_payload(structured, notes)
    if parsed is not None:
        return parsed
    for text in reversed(texts):
        parsed = parse_analyze_payload(text, notes)
        if parsed is not None:
            return parsed
    return None


def _normalize_payload(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "outcome" in data and isinstance(data["outcome"], str):
        out["outcome"] = data["outcome"]
    if isinstance(data.get("rootCause"), dict):
        from bugfix_contracts.analysis_report import normalize_root
        root = dict(data["rootCause"])
        candidates = (data.get("localization") or {}).get("candidates") or []
        allowed_refs = {f"candidate:{i}" for i in range(1, len(candidates)+1)}
        allowed_refs.update(str(c.get("path")) for c in candidates if c.get("path"))
        claims=[]
        for original in root.get("claims") or []:
            claim=dict(original)
            if claim.get("status") == "supported" and not all(str(ref).split(":",1)[0] in allowed_refs or str(ref) in allowed_refs for ref in claim.get("evidenceRefs") or []):
                claim["status"]="unverified"
            claims.append(claim)
        if "claims" in root:
            root["claims"]=claims
        out["rootCause"] = normalize_root(root)
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
        kept.append(_with_live_snippet(work_dir, cand))
    return kept


def _with_live_snippet(work_dir: str, cand: dict[str, Any]) -> dict[str, Any]:
    out = dict(cand)
    cited = str(out.get("snippet") or out.get("excerpt") or "").strip()
    if cited:
        out["snippet"] = cited
        return out
    path = _candidate_path(work_dir, out)
    if path is None or not path.is_file():
        return out
    body = path.read_text(encoding="utf-8", errors="replace")
    symbol = str(out.get("symbol") or "").strip()
    frag = extract_source_fragment(body, symbol)
    if frag:
        out["snippet"] = frag
        out["snippetSource"] = "extracted"
    return out


def _candidate_path(work_dir: str, cand: dict[str, Any]) -> Path | None:
    repo = cand.get("repoPath") or "."
    rel = Path(str(cand.get("path") or ""))
    root = Path(work_dir)
    try:
        return (root / repo / rel if repo not in (".", "") else root / rel).resolve()
    except OSError:
        return None


def extract_source_fragment(body: str, symbol: str, window: int = 8) -> str:
    if not symbol:
        return ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if symbol not in line:
            continue
        chunk = [ln for ln in lines[i : i + window] if ln.strip()]
        return "\n".join(chunk).strip()[:400]
    return ""


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
CodeGraph is navigation, not source of truth. After it returns a path or symbol you
MUST Read the current file in the worktree before citing it as evidence. Do not treat
graph excerpts as the live source. Fall back to Grep/Read/Glob only when CodeGraph is
unavailable or empty.
Ground claims in files you actually Read after graph navigation.
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
outcome, rootCause{summary,ruledOut,openQuestions,claims,questions}, proposedFix{summary,steps,targetFiles},
localization{candidates,notes}, blockers, confidence, suggestedVerify{steps,executed}.
rootCause.claims is an array of {claimId,statement,role:fact|hypothesis|conclusion,
status:supported|conditional|unverified|refuted,evidenceRefs,assumptions}.
Use evidenceRefs candidate:1, candidate:2, etc. pointing to localization candidates, or their exact path. A reference identifies supporting material; it does not by itself prove runtime causation.
rootCause.questions is an array (possibly empty) of {id,kind:blocking|choice|verification|follow_up,
reason,relatedClaimIds,requestedEvidence,category:product|fact|implementation,status:open|answered|resolved,
newEvidenceRefs}. openQuestions is its human-readable projection.
Use newEvidenceRefs candidate:1 / candidate:2 or the exact localization path; the program
maps those aliases onto this attempt's evidence IDs. Do not invent internal evidence IDs.
Only questions that change THIS repair target or mechanism are blocking/choice.
Product/fact blocking or choice questions cannot be marked resolved without a user
answer or an existing project rule cited by path. Ordinary implementation choices
must be decided by you with a concrete rationale and newEvidenceRefs; do not bounce them to the user.
If previousAttempt listed open questions, keep each id or set predecessorId.
Evidence snippets prove quotation accuracy, not causality. External device effects,
measured latency and runtime CSS behavior remain conditional without observation.
Respect the current expected behavior, especially user-confirmed changes. Do not
replace a confirmed removal requirement by fixing a different behavior. Separate
incidental robustness findings from this ticket's causal claims. If requirements
conflict, explain the conflict rather than changing the target.
Each localization.candidates[] item MUST include path and a snippet (verbatim 1-8
lines from a file you Read) of the failing fragment, plus why that fragment causes
the reported failure. Optional: symbol, excerpt. Omitting snippet is a locator only
and is not enough to authorize an edit.
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

    # 上游调查是 Agent-2 的产出，已经定位过文件和符号。它是**起点**而不是参考：
    # 重复发现同样的东西会白烧预算（实测首轮 25 轮撞顶，其中 5 次 codegraph
    # 探索、3 次读同一个上游已点名的文件）。
    upstream_block = ""
    investigation = req.investigation or {}
    if investigation:
        upstream_block = (
            "upstreamInvestigation: "
            f"{json.dumps(investigation, ensure_ascii=False)}\n"
            "上面是 Agent-2 的定位结果：已点名的 path/symbol 直接读，不必重新搜索。"
            "它标为 conditional / unverified 的部分仍需你验证——不要当成既定事实。\n"
        )
    # matchGap 是路由层的诊断（例如 no_path_token_overlap），与上游调查有无无关。
    # softStartLocalization.candidates 与 upstreamInvestigation.candidates 逐字相同，
    # 所以只保留这一条 notes，不重复整份候选列表。
    soft_notes = soft.get("notes") if isinstance(soft, dict) else ""
    if soft_notes:
        upstream_block += f"matchGap: {soft_notes}\n"

    # 首轮没有 previousAttempt，此时输出 `previousAttempt: {}` 再加一条
    # "If previousAttempt.analysisRef.path exists" 只会制造死指令。
    previous_block = ""
    if req.previous_attempt:
        previous_block = (
            f"previousAttempt: {json.dumps(req.previous_attempt, ensure_ascii=False)}\n"
            "If previousAttempt.analysisRef.path exists, Read it when you need the full first-round record. "
            "Do not drop confirmed answers or CURRENT ACCEPTANCE TARGET in any summary.\n"
        )

    return (
        "Analyze this defect and return the JSON object described in the system prompt.\n\n"
        f"defectId: {t.defectId}\n"
        f"title: {t.title}\n"
        f"pool: {t.pool}\n"
        f"testModule: {t.testModule}\n"
        f"titleTag: {t.titleTag}\n"
        f"intent: {t.intent}\n"
        f"intentRationale: {(t.intentRationale or '')[:400]}\n"
        f"sourceDocument: {t.sourceDocument.model_dump_json() if t.sourceDocument else None}\n"
        f"inputQuality: {t.inputQuality.model_dump_json()}\n"
        f"observed: {t.observed}\n"
        f"CURRENT ACCEPTANCE TARGET: {t.expected}\n"
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
        f"{upstream_block}"
        f"routerOutcomeHint: {req.routed.get('outcome')}\n"
        f"applyFix: {apply_flag}\n"
        f"{previous_block}"
    )
