from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional
from pathlib import Path

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_contracts.code_knowledge import DefectCodeMatch
from bugfix_platform.sdk.parse import parse_json_payload
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS, CodeGraphStatus
from bugfix_platform.sdk.skill_inject import InjectedSkill, cartography_skills_addon
from bugfix_platform.sdk.skills import skills_system_addon

CartographyMode = Literal["heuristic", "sdk"]

# 提示词里带给模型的匹配池票上限。启发式 medium 也会进（需 SDK 浅确认）。
MAX_PROMPT_TICKETS = 16
# 旧名：行为已改为全匹配池，不再表示「仅弱票」。
MAX_WEAK_PROMPT_TICKETS = MAX_PROMPT_TICKETS
_MATCH_POOL = frozenset({"strict", "locatable_only", "needs_info"})
# 无票数上下文时的兜底（兼容旧调用）；正常路径按票数预算。
DEFAULT_CARTOGRAPHY_MAX_TURNS = 24
# 地图/playbook 开销 + 每张进 prompt 票的配额。
# 覆盖率取决于进 prompt 的票；这是唯一能买深度的旋钮。
# led 实测（40 票 / 16 进 prompt）：2 轮/票 = 38 轮，摸不完 16 张；7 轮/票 = 118 轮。
DEFAULT_CARTOGRAPHY_BASE_TURNS = 6
DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET = 7
# 候选集完全相同的票达到这个数，说明打分并列、路径 token 没区分度（假 medium）。
SHARED_SIGNATURE_MIN_TICKETS = 3
_BUDGET_SUBTYPES = frozenset({"error_max_turns", "error_max_budget_usd"})
_SALVAGE_PROMPT = (
    "Stop exploring. Based only on what you already observed, return the JSON "
    "enrich object now. Incomplete is OK; set partial=true. Do not follow "
    "imports or name a fix locus. Do not call more tools unless required to emit JSON."
)

# Thorough read session: Bash + CodeGraph MCP; no mutate tools.
# Bash 在真实 CLI 路由验证完成前关闭（F05/S）。Read/Grep/Glob/CodeGraph 足够只读调查。
CARTOGRAPHY_TOOLS = ["Read", "Glob", "Grep", *CODEGRAPH_MCP_TOOLS]
DISALLOWED_TOOLS = ["Edit", "Write", "NotebookEdit", "MultiEdit"]

# Destructive / egress patterns for Bash (defense in depth; prompt also forbids mutation).
_BASH_DENY_RE = re.compile(
    r"""(?ix)
    (?:^|[;&|`]\s*|\$\()
    (?:
        rm\b|sudo\b|chmod\b|chown\b|mkfs\b|dd\b|truncate\b|
        git\s+(?:push|commit|rebase|reset|clean|tag|add|stash|checkout|switch|merge|cherry-pick|pull)|
        (?:npm|pnpm|yarn|bun)\s+(?:publish|install|add|uninstall|update)|
        pip(?:3)?\s+install|
        (?:curl|wget|nc|ncat|ssh|scp|rsync|ftp)\b|
        docker\b|kubectl\b|
        python(?:3)?\s+-m\s+pip\s+install
    )
    """
)


def _env_positive_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def cartography_turns_for_tickets(ticket_count: int) -> int:
    """``base + per_ticket * n`` — n is the match-pool count that enters the prompt."""
    n = max(0, int(ticket_count))
    base = _env_positive_int(
        "BUGFIX_CARTOGRAPHY_BASE_TURNS", DEFAULT_CARTOGRAPHY_BASE_TURNS
    )
    per = _env_positive_int(
        "BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET", DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET
    )
    return base + per * n


def resolve_cartography_max_turns(
    explicit: Optional[int] = None,
    *,
    weak_ticket_count: Optional[int] = None,
    ticket_count: Optional[int] = None,
) -> Optional[int]:
    """Return SDK ``max_turns`` or ``None`` for unlimited.

    - Request explicit ``>0`` → that value
    - Request explicit ``<=0`` → unlimited
    - Env ``BUGFIX_CARTOGRAPHY_MAX_TURNS`` set to a positive int → absolute override
    - Env ``0`` / ``none`` / ``unlimited`` → unlimited
    - Env empty + ``ticket_count`` / ``weak_ticket_count`` → ``base + per_ticket * n``
    - Env empty + no ticket count → ``DEFAULT_CARTOGRAPHY_MAX_TURNS`` (compat)
    """
    if explicit is not None:
        return None if explicit <= 0 else explicit
    raw = (os.environ.get("BUGFIX_CARTOGRAPHY_MAX_TURNS") or "").strip().lower()
    if raw in ("0", "none", "null", "unlimited", "inf", "infinite"):
        return None
    if raw != "":
        try:
            n = int(raw)
        except ValueError:
            n = DEFAULT_CARTOGRAPHY_MAX_TURNS
        return None if n <= 0 else n
    n = ticket_count if ticket_count is not None else weak_ticket_count
    if n is not None:
        return cartography_turns_for_tickets(n)
    return DEFAULT_CARTOGRAPHY_MAX_TURNS


def bash_command_allowed(command: str) -> tuple[bool, str]:
    """Whether a Bash tool command is allowed for Agent-2 cartography."""
    text = (command or "").strip()
    if not text:
        return False, "empty bash command"
    if _BASH_DENY_RE.search(text):
        return (
            False,
            "bash blocked: mutating, network, package-install, or VCS-write commands are not allowed in Agent-2",
        )
    if re.search(r"(>>|tee\b|python(?:3)?\s+-c\b|(?<![0-9])>\s*\S+)", text):
        return False, "bash blocked: redirects, tee, or python -c can write files"
    return True, ""


def _cartography_max_turns(default: int = 48) -> int:
    """Deprecated helper kept for callers; prefer ``resolve_cartography_max_turns``."""
    resolved = resolve_cartography_max_turns()
    return default if resolved is None else resolved


@dataclass
class CartographyRequest:
    work_dir: str
    defect_batch: DefectBatch
    baseline: CodeKnowledge
    # None → ticket-based budget (or env absolute override). <=0 = unlimited.
    max_turns: Optional[int] = None
    model: Optional[str] = None
    injected_skills: tuple[InjectedSkill, ...] = ()
    codegraph: Optional[CodeGraphStatus] = None
    investigation_only: bool = False
    artifact_dir: Optional[str | Path] = None
    group_id: Optional[str] = None
    call_id: Optional[str] = None


@dataclass
class CartographyResult:
    ok: bool
    knowledge: CodeKnowledge
    source: Literal["heuristic", "sdk", "sdk_fallback"]
    detail: Optional[str] = None
    skill_reads: list[str] = field(default_factory=list)
    turns: Optional[int] = None
    cost: Optional[float] = None


CartographyRunner = Callable[[CartographyRequest], CartographyResult]


def cartography_mode_from_env(explicit: Optional[str] = None) -> CartographyMode:
    raw = (explicit or os.environ.get("BUGFIX_CARTOGRAPHY_MODE") or "").strip().lower()
    if raw in ("sdk", "heuristic"):
        return raw  # type: ignore[return-value]
    if has_credentials():
        return "sdk"
    return "heuristic"


def cartography_allowed_tools() -> list[str]:
    """S 未通过前不启用 Bash。"""
    return [name for name in CARTOGRAPHY_TOOLS if name != "Bash"]


def _cartography_hooks() -> dict[str, list[Any]]:
    """PreToolUse 在 SDK 真正执行前拦截写 Bash；whole-tool allow 不能当唯一闸。"""
    try:
        from claude_agent_sdk import HookMatcher
    except ImportError:
        return {}

    async def pre_tool_use(hook_input: Any, _tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
        payload = hook_input if isinstance(hook_input, dict) else {}
        tool = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else payload
        if tool == "Bash" or "command" in (tool_input or {}):
            cmd = str((tool_input or {}).get("command") or "")
            ok, reason = bash_command_allowed(cmd)
            if not ok:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
        return {}

    return {"PreToolUse": [HookMatcher(matcher="Bash", hooks=[pre_tool_use], on_failure="block")]}


async def _can_use_cartography_tool(
    tool_name: str,
    input_data: dict[str, Any],
    _context: Any,
) -> Any:
    from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

    if tool_name == "Bash":
        cmd = str(input_data.get("command") or input_data.get("cmd") or "")
        ok, reason = bash_command_allowed(cmd)
        if not ok:
            return PermissionResultDeny(message=reason)
    return PermissionResultAllow()


def is_weak_match(match: Any, entry_points: list[str] | None = None) -> bool:
    """Whether SDK should try to improve this ticket's candidates.

    Weak = empty / low confidence / candidates are only architecture entryPoints
    / ``why`` is dual-entry-only (the false-medium baseline).
    """
    if match is None:
        return True
    if isinstance(match, dict):
        cands = list(match.get("candidates") or [])
        conf = str(match.get("confidence") or "low")
    else:
        cands = list(getattr(match, "candidates", None) or [])
        conf = str(getattr(match, "confidence", None) or "low")
    if not cands or conf == "low":
        return True
    entries = {_norm_rel(ep) for ep in (entry_points or []) if ep}

    def _cand_path(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("path") or "")
        return str(getattr(item, "path", "") or "")

    def _cand_why(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("why") or "")
        return str(getattr(item, "why", "") or "")

    paths = [_norm_rel(_cand_path(c)) for c in cands]
    if entries and paths and all(p in entries for p in paths):
        return True
    whys = [_cand_why(c).lower() for c in cands]
    if whys and all("dual-entry" in w for w in whys):
        return True
    return False


def _norm_rel(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./").lower()


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


def _parse_session_json(structured: Any, texts: list[str]) -> Optional[dict[str, Any]]:
    from bugfix_platform.sdk.match_payload import find_business_envelope

    envelope, _ref = find_business_envelope(structured=structured, texts=texts)
    if envelope is not None:
        return envelope
    parsed = parse_json_payload(structured)
    if parsed is not None:
        return parsed
    for text in reversed(texts):
        parsed = parse_json_payload(text)
        if parsed is not None:
            return parsed
    return None


def _billing(
    turns: int | None, cost: float | None, terminal: str | None
) -> str:
    """``turns=17; reason=completed; cost=$0.42`` —— 写进产物，让成本可复核。"""
    bits: list[str] = []
    if turns is not None:
        bits.append(f"turns={turns}")
    if terminal:
        bits.append(f"reason={terminal}")
    if cost is not None:
        bits.append(f"cost=${cost:.4f}" if cost < 0.01 else f"cost=${cost:.2f}")
    return "; ".join(bits)


@dataclass
class CartographyResponse:
    parsed: dict[str, Any] | None
    terminal: str | None = None
    budget_stop: bool = False
    turns: int | None = None
    cost: float | None = None
    skill_reads: list[str] = field(default_factory=list)
    observed_paths: list[str] = field(default_factory=list)
    error: str | None = None
    recorder: Any = None


def query_cartography(
    req: CartographyRequest,
    *,
    create_recorder: Callable[[int | None], Any] | None = None,
    record_repair: Callable[[str, str, str], None] | None = None,
) -> CartographyResponse:
    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        return CartographyResponse(None, error=f"claude-agent-sdk not installed ({err}); fell back to heuristic")

    prompt_pairs = select_prompt_tickets(req)
    prompt = _build_prompt(req, prompt_pairs=prompt_pairs)
    model = req.model or os.environ.get("ANTHROPIC_MODEL") or None
    if req.injected_skills:
        system_prompt = _SYSTEM_PROMPT + cartography_skills_addon(req.injected_skills)
    else:
        system_prompt = _SYSTEM_PROMPT + skills_system_addon(
            (
                "code-cartography",
                "monorepo-workspace",
                "electron-process-boundary",
                "hierarchical-localization",
            )
        )
    max_turns = resolve_cartography_max_turns(
        req.max_turns, ticket_count=len(prompt_pairs)
    )

    cg = req.codegraph

    def _make_options(*, resume: str | None = None, turns: Optional[int] = None) -> Any:
        hooks = _cartography_hooks()
        tools = cartography_allowed_tools()
        if not hooks:
            tools = [name for name in tools if name != "Bash"]
        kwargs: dict[str, Any] = {
            "cwd": req.work_dir,
            "system_prompt": system_prompt,
            "allowed_tools": tools,
            "disallowed_tools": list(DISALLOWED_TOOLS),
            "permission_mode": "dontAsk",
            "max_turns": turns if turns is not None else max_turns,
            "model": model,
            "can_use_tool": _can_use_cartography_tool,
            "hooks": hooks,
        }
        if cg is not None:
            kwargs.update(cg.mcp_option_kwargs(req.work_dir))
        if resume:
            kwargs["resume"] = resume
        try:
            return ClaudeAgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("resume", None)
            kwargs.pop("strict_mcp_config", None)
            kwargs.pop("hooks", None)
            kwargs["allowed_tools"] = [name for name in kwargs["allowed_tools"] if name != "Bash"]
            try:
                return ClaudeAgentOptions(**kwargs)
            except TypeError:
                kwargs.pop("mcp_servers", None)
                kwargs.pop("can_use_tool", None)
                return ClaudeAgentOptions(**kwargs)

    texts: list[str] = []
    result_text = ""
    structured: Any = None
    turns: int | None = None
    cost: float | None = None
    terminal: str | None = None
    session_id: str | None = None
    budget_stop = False
    skill_reads: set[str] = set()
    pending_skill_reads: dict[str, str] = {}
    observed_paths: list[str] = []
    pending_observe: dict[str, str] = {}
    recorder = create_recorder(max_turns) if create_recorder is not None else None

    def _tool_event(block: Any) -> dict[str, Any]:
        payload = {
            "name": getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else None),
            "id": getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else None),
            "tool_use_id": getattr(block, "tool_use_id", None) or (block.get("tool_use_id") if isinstance(block, dict) else None),
            "input": getattr(block, "input", None) if not isinstance(block, dict) else block.get("input"),
            "content": getattr(block, "content", None) if not isinstance(block, dict) else block.get("content"),
        }
        return {k: v for k, v in payload.items() if v is not None}

    def observe_reads(message: Any) -> None:
        from bugfix_platform.sdk.match_payload import apply_tool_observation
        for block in getattr(message, "content", []) or []:
            apply_tool_observation(pending_observe, observed_paths, block, req.work_dir)
            name = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else None)
            params = getattr(block, "input", None) or (block.get("input") if isinstance(block, dict) else {}) or {}
            if name == "Read":
                ref = params.get("file_path")
                if ref:
                    path = Path(ref)
                    if not path.is_absolute():
                        path = Path(req.work_dir) / path
                    resolved = str(path.resolve())
                    if any(resolved == str(s.skill_md.resolve()) for s in req.injected_skills):
                        pending_skill_reads[str(getattr(block, "id", ""))] = resolved
            use_id = str(getattr(block, "tool_use_id", "") or "")
            if use_id in pending_skill_reads and not getattr(block, "is_error", False) and getattr(block, "content", None):
                skill_reads.add(pending_skill_reads.pop(use_id))

    async def _drive(prompt_text: str, opts: Any) -> None:
        nonlocal result_text, structured, turns, cost, terminal, session_id, budget_stop
        async for message in query(prompt=prompt_text, options=opts):
            observe_reads(message)
            text = _message_text(message)
            if text.strip():
                texts.append(text)
            if recorder is not None:
                kind = "result" if isinstance(message, ResultMessage) else "assistant"
                tools = [_tool_event(b) for b in (getattr(message, "content", None) or [])]
                recorder.append_event(
                    {
                        "kind": kind,
                        "text": text,
                        "tools": [t for t in tools if t],
                        "structured_output": getattr(message, "structured_output", None),
                        "is_error": bool(getattr(message, "is_error", False)),
                    }
                )
            if not isinstance(message, ResultMessage):
                continue
            turns = message.num_turns
            cost = message.total_cost_usd
            terminal = message.terminal_reason
            session_id = getattr(message, "session_id", None) or session_id
            structured = message.structured_output
            result_text = message.result or ""
            if _budget_exhausted(message):
                budget_stop = True
                continue
            if message.is_error:
                raise RuntimeError(
                    "; ".join(message.errors or []) or message.result or "cartography SDK error"
                )

    try:
        anyio.run(_drive, prompt, _make_options())
    except Exception as err:  # noqa: BLE001
        if recorder is not None:
            recorder.append_event({"kind": "error", "text": str(err)})
            candidates = [t for t in texts if t.strip()]
            if structured is not None:
                candidates.insert(0, json.dumps(structured, default=str))
            try:
                recorder.save_parse_inputs(candidates)
                recorder.save_response(
                    {
                        "structured_output": structured,
                        "result_text": result_text,
                        "errors": [str(err)],
                        "parse_candidates": candidates,
                    }
                )
            except OSError:
                recorder.artifact_error = "unwritable"
            recorder.fail("sdk_error", str(err))
        if not budget_stop:
            return CartographyResponse(
                None, terminal, budget_stop, turns, cost, sorted(skill_reads), observed_paths,
                error=f"sdk cartography failed: {err}", recorder=recorder,
            )

    if recorder is not None:
        candidates = list(texts)
        if result_text:
            candidates.append(result_text)
        try:
            recorder.save_parse_inputs(candidates)
            recorder.save_response(
                {
                    "structured_output": structured,
                    "result_text": result_text,
                    "errors": [],
                    "parse_candidates": candidates,
                }
            )
        except OSError as err:
            recorder.fail("artifact_error", str(err))

    parsed = _parse_session_json(structured, texts)
    remaining_turns = None
    if max_turns is not None and turns is not None:
        remaining_turns = max(0, int(max_turns) - int(turns))
    if remaining_turns is None:
        salvage_turns = 2
    else:
        salvage_turns = min(2, remaining_turns)
    if parsed is None and budget_stop and session_id and salvage_turns > 0:
        salvage_texts: list[str] = []

        async def _salvage() -> None:
            nonlocal structured, result_text, turns, cost, terminal
            async for message in query(
                prompt=_SALVAGE_PROMPT,
                options=_make_options(resume=session_id, turns=salvage_turns),
            ):
                observe_reads(message)
                text = _message_text(message)
                if text.strip():
                    salvage_texts.append(text)
                    if recorder is not None:
                        recorder.append_event({"kind": "salvage", "text": text})
                if not isinstance(message, ResultMessage):
                    continue
                extra_turns = message.num_turns
                if extra_turns is not None:
                    turns = (turns or 0) + extra_turns
                if message.total_cost_usd is not None:
                    cost = (cost or 0.0) + float(message.total_cost_usd)
                structured = message.structured_output
                result_text = message.result or ""
                if message.is_error and not _budget_exhausted(message):
                    raise RuntimeError(
                        "; ".join(message.errors or [])
                        or message.result
                        or "cartography salvage error"
                    )

        try:
            anyio.run(_salvage)
        except Exception as salvage_err:  # noqa: BLE001
            if recorder is not None:
                recorder.append_event({"kind": "salvage_error", "text": str(salvage_err)})
        if recorder is not None:
            try:
                if record_repair is not None:
                    record_repair(recorder.call_id, "\n".join(texts), "\n".join(salvage_texts))
                recorder.save_response(
                    {
                        "phase": "format_repair",
                        "structured_output": structured,
                        "result_text": result_text,
                        "parse_candidates": salvage_texts,
                    }
                )
            except OSError as err:
                recorder.fail("artifact_error", str(err))
        texts.extend(salvage_texts)
        parsed = _parse_session_json(structured, texts)

    if budget_stop and not terminal:
        terminal = "max_turns"
    return CartographyResponse(
        parsed, terminal, budget_stop, turns, cost, sorted(skill_reads), observed_paths, recorder=recorder,
    )


PROFILE_READING_PLAYBOOK = {
    "micro_frontend": (
        "micro_frontend read order: (1) .gitmodules paths that contain vue.app.js, "
        "src/index.html mount divs, build/config/modules.js — that IS the module list; "
        "do not treat src/Common as a micro-app. (2) root-application.js for PC vs H5 "
        "(nature===h5 → Common/mobile/init). (3) localize testModule to src/<App>/ first; "
        "follow loadModuleExports('X') across apps. (4) @/ is not always src/."
    ),
    "device_web": (
        "device_web read order: (1) split PC vs mobile — main-pc.js / main-mobile.js and "
        "Router/{pc,mobile}.js. (2) src/<Business>/ directories (Config, Preview, …) are "
        "route modules in one SPA; drill view/<subdomain> (Config.snap) into modules. "
        "Router/**/{pc,mobile}.js are route tables, not fix loci. "
        "(3) greyed-out / "
        "missing-feature defects: read Common/service/device.js before views. (4) real "
        "bridge is jsWebControl, not a folder named bridge. (5) do not look for vue.app.js. "
        "(6) index.asp is host, not architecture."
    ),
    "electron_node": (
        "electron_node read order: (1) follow package.json main, loadFile/loadURL, and "
        "contextBridge.exposeInMainWorld — never classify by a file named main.ts. "
        "(2) IPC prefix → controller/<domain>/ is the localization jump. "
        "(3) renderer is web/src boot, not views/*. (4) keep driver/ addon/; "
        "fork(subsystem) may leave this repo. (5) vite-plugin-electron alone is not Electron."
    ),
    "unknown": (
        "cartographyProfile is unknown: do not guess electron / micro-frontend / device-web. "
        "Read CLAUDE.md and overlay skills, keep architecture shallow, mark partial."
    ),
}


def profile_reading_playbook(profile: str | None) -> str:
    """Type-specific read order for SDK / SOP. Profile is caller-supplied."""
    key = (profile or "unknown").strip() or "unknown"
    return PROFILE_READING_PLAYBOOK.get(key, PROFILE_READING_PLAYBOOK["unknown"])


_SYSTEM_PROMPT = """You are Agent-2 Code Cartographer for an automated bugfix pipeline.
Your job is to thicken the architecture map and SHALLOW-PASS every listed match-pool
ticket (confirm or replace heuristic candidates). Agent-3 follows imports and names
the fix locus. You do not.

Tools: CodeGraph MCP (preferred), Read, Glob, and Grep. Bash is disabled.
When CodeGraph is ready (codegraph_explore / codegraph_node), the first structural,
symbol, or ticket-confirm tool call MUST be codegraph_explore (or node/callers).
It is a pre-built local index; do not re-grep what it already returned. Treat
CodeGraph source excerpts as already Read. Fall back to Grep/Read/Glob only when
CodeGraph is unavailable or returns empty. specAtlas.entries are path indexes
(kind=doc_ref); do not copy spec markdown into entries, notes, or conventions.
Do not call Bash. NEVER mutate the repo: no edit/write tools, no git write,
    no install, no network, no rm/chmod.

cartographyProfile is CALLER-SUPPLIED. Do not reclassify the repo.

How to work:
1) Follow the profile reading playbook, then CLAUDE.md / overlay skills.
   Overlay skills have HIGHEST PRIORITY over package SOP on read order, layout, aliases.
2) Thicken architecture (entryPoints, route/business modules, runtime shape).
   Prefer CodeGraph explore for module/symbol maps; catalog files next.
   Do not walk the whole repo file-by-file. Do not read trellis/spec bodies.
3) Investigate EVERY ticket in this bounded matchPoolTickets group. Cap 3 real paths
   per ticket; 0 is valid — do not pad. Empty is better than a wrong path or
   sibling stubs (mixin.js / isapi.js with no logic).
   CodeGraph MUST be used for ticket localization when ready; set
   candidate.source = "codegraph" when the path came from CodeGraph.
   Heuristic medium/high candidates are
   UNVERIFIED path-token hits: confirm with CodeGraph (or Grep/Read), replace
   if wrong, or clear them. Do not copy them blindly.
   candidate.why = why the path resembles the title/module — not a root cause,
   facts must cite actual code; hypotheses remain tentative. Use bounded investigation of imports/callers; do not exhaust the repository per ticket.
   Route tables, shells, hosts and entryPoints are not fix loci. If the ticket
   names web/PC, do not return /mobile/ or /h5/ exclusive files.
4) Leave a turn to emit JSON. Incomplete is OK; set partial=true.

Return one JSON object (optionally in a ```json fence) with any of:
secondaryHints, techStack{languages,frameworks,notes},
architecture{summary,entryPoints,modules[{id,path,role,shared,notes}]},
conventions{fromRules}, boundSkills,
defectCodeMatches[{defectId,candidates[{repoPath,path,symbol,why,source}],confidence,searchedScopes,facts,hypotheses,ruledOut,openQuestions,nextChecks}],
partial.
Do not change cartographyProfile. Do not add keys that are not listed above: an
entry that does not fit that shape is dropped before delivery, losing the whole
ticket. ``gap`` is not yours to write.
candidate source must be one of: codegraph, grep, heuristic, claude_md, model_reported.
facts is a list of objects {claim, reference?, validity?, source?}; a non-empty string is stored as an unverified claim. Never set source=tool_observed or validity=reference_verified.
repoPath = the repo root as listed in repoRoots; use "." for a single-repo workDir.
path = the file path relative to that root. Never put the file path in both fields:
a candidate whose repoPath/path cannot be resolved is dropped before delivery.
"""


def _candidate_signature(match: Any) -> tuple[str, ...] | None:
    """候选集归一后的指纹（路径排序）；少于 2 个候选不值得比较。"""
    cands = list(getattr(match, "candidates", None) or [])
    if len(cands) < 2:
        return None
    return tuple(sorted(_norm_rel(getattr(c, "path", "") or "") for c in cands))


def _shared_signatures(matches: list[Any]) -> set[tuple[str, ...]]:
    """被至少 ``SHARED_SIGNATURE_MIN_TICKETS`` 张票共用的候选集指纹。

    多个不同的缺陷拿到完全相同的候选，说明打分是并列的、路径 token 没区分度
    （中文 testModule/标题打不中 ASCII 路径时尤其明显）。这种“有候选”并不是
    定位，不能因为 ``len(candidates) >= 2`` 就判成不弱。
    """
    counts: dict[tuple[str, ...], int] = {}
    for match in matches:
        sig = _candidate_signature(match)
        if sig is not None:
            counts[sig] = counts.get(sig, 0) + 1
    return {sig for sig, n in counts.items() if n >= SHARED_SIGNATURE_MIN_TICKETS}


def _investigation_complete(match: DefectCodeMatch) -> bool:
    """complete = 可追溯代码观察或实际检索，不是 facts 非空。"""
    if match.storageStatus == "artifact_error":
        return False
    if match.acceptanceStatus == "rejected":
        return False
    observed = [s for s in (match.observedScopes or []) if str(s).strip()]
    if observed:
        return True
    for fact in match.facts or []:
        ref = getattr(fact, "reference", None)
        if ref is None and isinstance(fact, dict):
            ref = fact.get("reference")
        snippet = getattr(ref, "snippet", None) if ref is not None and not isinstance(ref, dict) else (ref or {}).get("snippet") if isinstance(ref, dict) else None
        validity = getattr(fact, "validity", None) or (fact.get("validity") if isinstance(fact, dict) else None)
        if snippet and validity == "reference_verified":
            return True
    return False


def investigated_ids_from_parsed(parsed: dict[str, Any] | None) -> list[str]:
    """只把模型实际返回的票算作已调查，不把 prompt 列表整批记 complete。"""
    out: list[str] = []
    for item in list((parsed or {}).get("defectCodeMatches") or []):
        if isinstance(item, dict) and item.get("defectId"):
            out.append(str(item["defectId"]))
    return out


def annotate_investigation_coverage(
    matches: list[DefectCodeMatch],
    *,
    prompt_ids: list[str],
    investigated_ids: list[str] | tuple[str, ...] = (),
) -> list[DefectCodeMatch]:
    """未进 prompt 的票显式 ``not_investigated``，禁止整批假完成。"""
    in_prompt = {str(x) for x in prompt_ids}
    investigated = {str(x) for x in investigated_ids}
    out: list[DefectCodeMatch] = []
    for match in matches:
        did = match.defectId
        if did not in in_prompt:
            status = "not_investigated"
        elif did in investigated:
            status = "complete" if _investigation_complete(match) else "partial"
        else:
            status = "search_draft" if match.candidates else "failed"
        out.append(match.model_copy(update={"investigationStatus": status}))
    return out


def select_prompt_tickets(
    req: CartographyRequest,
) -> list[tuple[Any, Any]]:
    """匹配池票选取：空/弱 → 并列假 medium → 其余启发式 medium；最多 ``MAX_PROMPT_TICKETS``。

    启发式「强」命中也进 prompt（需浅确认）；名额不够时弱票优先。
    返回 ``[(ticket, match), ...]``，与进 prompt / turn 预算共用。
    """
    entries = list(req.baseline.architecture.entryPoints)
    by_id = {m.defectId: m for m in req.baseline.defectCodeMatches}
    shared = _shared_signatures(req.baseline.defectCodeMatches)
    genuine: list[tuple[Any, Any]] = []
    ambiguous: list[tuple[Any, Any]] = []
    heuristic_hits: list[tuple[Any, Any]] = []
    for t in req.defect_batch.tickets:
        if t.pool not in _MATCH_POOL:
            continue
        match = by_id.get(t.defectId)
        if match is None or is_weak_match(match, entries):
            genuine.append((t, match))
        elif _candidate_signature(match) in shared:
            ambiguous.append((t, match))
        else:
            heuristic_hits.append((t, match))
    return (genuine + ambiguous + heuristic_hits)[:MAX_PROMPT_TICKETS]


def select_weak_tickets(req: CartographyRequest) -> list[tuple[Any, Any]]:
    """兼容旧名；等同 :func:`select_prompt_tickets`。"""
    return select_prompt_tickets(req)


def _build_prompt(
    req: CartographyRequest,
    *,
    prompt_pairs: list[tuple[Any, Any]] | None = None,
    weak_pairs: list[tuple[Any, Any]] | None = None,
) -> str:
    pairs = (
        prompt_pairs
        if prompt_pairs is not None
        else weak_pairs
        if weak_pairs is not None
        else select_prompt_tickets(req)
    )
    entries = list(req.baseline.architecture.entryPoints)
    pool_tickets = []
    pool_matches = []
    for t, match in pairs:
        rationale = (t.intentRationale or "").strip()
        unverified = match is not None and not is_weak_match(match, entries)
        pool_tickets.append(
            {
                "defectId": t.defectId,
                "sourceDocument": t.sourceDocument.model_dump() if t.sourceDocument else None,
                "observed": t.observed, "expected": t.expected, "steps": t.steps,
                "title": t.title,
                "pool": t.pool,
                "testModule": t.testModule,
                "titleTag": t.titleTag,
                "intent": t.intent,
                "intentRationale": rationale[:400] or None,
                # 启发式 medium 路径命中 ≠ 可信定位；提示模型必须确认或清空。
                "heuristicUnverified": unverified,
            }
        )
        if match is not None:
            payload = match.model_dump()
            # ``gap`` 是机器枚举；作为示例给出去，模型会把它当自由文本填回来。
            payload.pop("gap", None)
            if unverified and payload.get("confidence") in ("medium", "high"):
                # 进 prompt 时降权，避免模型把 baseline medium 当真理照抄。
                payload["confidence"] = "low"
            pool_matches.append(payload)
    budget = resolve_cartography_max_turns(req.max_turns, ticket_count=len(pairs))
    baseline = {
        "cartographyProfile": req.baseline.cartographyProfile,
        "secondaryHints": req.baseline.secondaryHints,
        "techStack": req.baseline.techStack.model_dump(),
        "architecture": req.baseline.architecture.model_dump(),
        "conventions": req.baseline.conventions.model_dump(),
        "boundSkills": req.baseline.boundSkills,
        "defectCodeMatches": pool_matches,
        "partial": req.baseline.partial,
    }
    playbook = profile_reading_playbook(req.baseline.cartographyProfile)
    cg = req.codegraph
    cg_line = (
        cg.prompt_roots_line()
        if cg is not None
        else "codeGraph: unavailable — use Grep/Read/Glob only"
    )
    return (
        ("Reuse the supplied repository map; do not rebuild architecture. Investigate EVERY listed "
         if req.investigation_only else "Build the repository map once from the playbook, then investigate EVERY listed ")
        +
        "match-pool ticket (max 3 paths each; 0 is valid, do not pad). "
        "Prefer CodeGraph when ready. heuristicUnverified=true means baseline "
        "candidates are untrusted — confirm, replace, or clear. Catalog files "
        "are usually navigation; follow a bounded relevant call chain when supported. Return the "
        "JSON enrich object before you run out of turns.\n\n"
        f"productLine: {req.defect_batch.productLine}\n"
        f"workDir: {req.work_dir}\n"
        f"cartographyProfile: {req.baseline.cartographyProfile} (caller-supplied; do not change)\n"
        f"readingPlaybook: {playbook}\n"
        f"{cg_line}\n"
        f"turnBudget: {budget} "
        f"(base={_env_positive_int('BUGFIX_CARTOGRAPHY_BASE_TURNS', DEFAULT_CARTOGRAPHY_BASE_TURNS)}"
        f" + perTicket={_env_positive_int('BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET', DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET)}"
        f" × promptTickets={len(pairs)})\n"
        f"injectedSkills: {json.dumps([s.name for s in req.injected_skills], ensure_ascii=False)}\n"
        f"matchPoolTickets: {json.dumps(pool_tickets, ensure_ascii=False)}\n"
        f"baseline: {json.dumps(baseline, ensure_ascii=False)}\n"
    )
