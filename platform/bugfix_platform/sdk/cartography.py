from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from bugfix_contracts import CodeKnowledge, DefectBatch, validate_code_knowledge
from bugfix_platform.sdk.parse import parse_json_payload
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.skill_inject import InjectedSkill, cartography_skills_addon
from bugfix_platform.sdk.skills import skills_system_addon

CartographyMode = Literal["heuristic", "sdk"]

# 提示词里带给模型的弱票上限。强匹配票不进 SDK prompt。
MAX_PROMPT_TICKETS = 8
MAX_WEAK_PROMPT_TICKETS = 8
DEFAULT_CARTOGRAPHY_MAX_TURNS = 24
_BUDGET_SUBTYPES = frozenset({"error_max_turns", "error_max_budget_usd"})
_SALVAGE_PROMPT = (
    "Stop exploring. Based only on what you already observed, return the JSON "
    "enrich object now. Incomplete is OK; set partial=true. Do not follow "
    "imports or name a fix locus. Do not call more tools unless required to emit JSON."
)

# Thorough read session: Bash allowed for read-only exploration; no mutate tools.
CARTOGRAPHY_TOOLS = ["Read", "Glob", "Grep", "Bash"]
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


def resolve_cartography_max_turns(explicit: Optional[int] = None) -> Optional[int]:
    """Return SDK ``max_turns`` or ``None`` for unlimited.

    - Request explicit ``>0`` → that value
    - Request explicit ``<=0`` → unlimited
    - Env empty → ``DEFAULT_CARTOGRAPHY_MAX_TURNS`` (24)
    - Env ``0`` / ``none`` / ``unlimited`` → unlimited
    - Env positive int → that value
    """
    if explicit is not None:
        return None if explicit <= 0 else explicit
    raw = (os.environ.get("BUGFIX_CARTOGRAPHY_MAX_TURNS") or "").strip().lower()
    if raw in ("0", "none", "null", "unlimited", "inf", "infinite"):
        return None
    if raw == "":
        return DEFAULT_CARTOGRAPHY_MAX_TURNS
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_CARTOGRAPHY_MAX_TURNS
    return None if n <= 0 else n


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
    # None → resolve from env (default 24). <=0 also means unlimited.
    max_turns: Optional[int] = None
    model: Optional[str] = None
    injected_skills: tuple[InjectedSkill, ...] = ()


@dataclass
class CartographyResult:
    ok: bool
    knowledge: CodeKnowledge
    source: Literal["heuristic", "sdk", "sdk_fallback"]
    detail: Optional[str] = None


CartographyRunner = Callable[[CartographyRequest], CartographyResult]


def cartography_mode_from_env(explicit: Optional[str] = None) -> CartographyMode:
    raw = (explicit or os.environ.get("BUGFIX_CARTOGRAPHY_MODE") or "").strip().lower()
    if raw in ("sdk", "heuristic"):
        return raw  # type: ignore[return-value]
    if has_credentials():
        return "sdk"
    return "heuristic"


def create_cartography_runner(mode: Optional[CartographyMode] = None) -> CartographyRunner:
    resolved = mode or cartography_mode_from_env()
    if resolved == "sdk":
        return run_claude_cartography
    return heuristic_cartography


def heuristic_cartography(req: CartographyRequest) -> CartographyResult:
    """No LLM: return baseline; annotate architecture.summary."""
    data = req.baseline.model_dump()
    arch = dict(data.get("architecture") or {})
    summary = (arch.get("summary") or "").rstrip()
    note = "cartography enrich skipped (heuristic mode)"
    if note not in summary:
        arch["summary"] = f"{summary}; {note}" if summary else note
    data["architecture"] = arch
    return CartographyResult(
        ok=True,
        knowledge=validate_code_knowledge(data),
        source="heuristic",
    )


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


def _sdk_keep_baseline(req: CartographyRequest, billing: str) -> CartographyResult:
    """触顶且无 JSON：保留进 SDK 前的启发式图，不标 sdk_fallback。"""
    data = req.baseline.model_dump()
    data["partial"] = True
    return CartographyResult(
        ok=True,
        knowledge=validate_code_knowledge(data),
        source="sdk",
        detail=billing or None,
    )


def run_claude_cartography(req: CartographyRequest) -> CartographyResult:
    """Claude Agent SDK session: thicken architecture + weak path matches."""
    if not has_credentials():
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = (
            "no Anthropic credentials in env (ANTHROPIC_API_KEY / "
            "ANTHROPIC_AUTH_TOKEN); fell back to heuristic"
        )
        return fallback

    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = f"claude-agent-sdk not installed ({err}); fell back to heuristic"
        return fallback

    prompt = _build_prompt(req)
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
    max_turns = resolve_cartography_max_turns(req.max_turns)

    def _make_options(*, resume: str | None = None, turns: Optional[int] = None) -> Any:
        kwargs: dict[str, Any] = {
            "cwd": req.work_dir,
            "system_prompt": system_prompt,
            "allowed_tools": list(CARTOGRAPHY_TOOLS),
            "disallowed_tools": list(DISALLOWED_TOOLS),
            "permission_mode": "dontAsk",
            "max_turns": turns if turns is not None else max_turns,
            "model": model,
            "can_use_tool": _can_use_cartography_tool,
        }
        if resume:
            kwargs["resume"] = resume
        try:
            return ClaudeAgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("resume", None)
            return ClaudeAgentOptions(**kwargs)

    texts: list[str] = []
    result_text = ""
    structured: Any = None
    turns: int | None = None
    cost: float | None = None
    terminal: str | None = None
    session_id: str | None = None
    budget_stop = False

    async def _drive(prompt_text: str, opts: Any) -> None:
        nonlocal result_text, structured, turns, cost, terminal, session_id, budget_stop
        async for message in query(prompt=prompt_text, options=opts):
            text = _message_text(message)
            if text.strip():
                texts.append(text)
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
        if not budget_stop:
            fallback = heuristic_cartography(req)
            fallback.source = "sdk_fallback"
            billing = _billing(turns, cost, terminal)
            fallback.detail = f"sdk cartography failed: {err}" + (
                f"; {billing}" if billing else ""
            )
            return fallback

    parsed = _parse_session_json(structured, texts)
    if parsed is None and budget_stop and session_id:
        salvage_texts: list[str] = []

        async def _salvage() -> None:
            nonlocal structured, result_text, turns, cost, terminal
            async for message in query(
                prompt=_SALVAGE_PROMPT,
                options=_make_options(resume=session_id, turns=2),
            ):
                text = _message_text(message)
                if text.strip():
                    salvage_texts.append(text)
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

        first_turns, first_cost, first_terminal = turns, cost, terminal
        try:
            anyio.run(_salvage)
        except Exception:  # noqa: BLE001
            pass
        texts.extend(salvage_texts)
        parsed = _parse_session_json(structured, texts)
        if parsed is None:
            turns, cost, terminal = first_turns, first_cost, first_terminal

    if budget_stop and not terminal:
        terminal = "max_turns"
    billing = _billing(turns, cost, terminal)

    if parsed is not None:
        try:
            merged = _merge_enrichment(req.baseline, parsed)
            if budget_stop:
                merged["partial"] = True
            knowledge = validate_code_knowledge(merged)
        except Exception as err:  # noqa: BLE001
            if budget_stop:
                return _sdk_keep_baseline(req, billing)
            fallback = heuristic_cartography(req)
            fallback.source = "sdk_fallback"
            fallback.detail = f"enriched code-knowledge invalid: {err}"
            return fallback
        return CartographyResult(
            ok=True, knowledge=knowledge, source="sdk", detail=billing or None
        )

    if budget_stop:
        return _sdk_keep_baseline(req, billing)

    fallback = heuristic_cartography(req)
    fallback.source = "sdk_fallback"
    fallback.detail = "sdk returned no parseable JSON cartography"
    return fallback


def _merge_enrichment(baseline: CodeKnowledge, parsed: dict[str, Any]) -> dict[str, Any]:
    data = baseline.model_dump()
    # Optional top-level overrides that stay within schema.
    # cartographyProfile is caller-supplied; never let the SDK reclassify.
    if isinstance(parsed.get("secondaryHints"), list):
        data["secondaryHints"] = [str(x) for x in parsed["secondaryHints"]][:20]
    if isinstance(parsed.get("techStack"), dict):
        tech = dict(data.get("techStack") or {})
        incoming = parsed["techStack"]
        for key in ("languages", "frameworks"):
            if isinstance(incoming.get(key), list) and incoming[key]:
                tech[key] = [str(x) for x in incoming[key]]
        if isinstance(incoming.get("notes"), str) and incoming["notes"].strip():
            tech["notes"] = incoming["notes"]
        data["techStack"] = tech
    if isinstance(parsed.get("architecture"), dict):
        arch = dict(data.get("architecture") or {})
        incoming = parsed["architecture"]
        if isinstance(incoming.get("summary"), str) and incoming["summary"].strip():
            arch["summary"] = incoming["summary"]
        if isinstance(incoming.get("entryPoints"), list):
            arch["entryPoints"] = [str(x) for x in incoming["entryPoints"]][:40]
        if isinstance(incoming.get("modules"), list) and incoming["modules"]:
            arch["modules"] = incoming["modules"]
        data["architecture"] = arch
    if isinstance(parsed.get("conventions"), dict):
        conv = dict(data.get("conventions") or {})
        incoming = parsed["conventions"]
        if isinstance(incoming.get("fromClaudeMd"), list) and incoming["fromClaudeMd"]:
            conv["fromClaudeMd"] = [str(x) for x in incoming["fromClaudeMd"]][:40]
        if isinstance(incoming.get("fromRules"), list) and incoming["fromRules"]:
            conv["fromRules"] = [str(x) for x in incoming["fromRules"]][:40]
        data["conventions"] = conv
    if isinstance(parsed.get("boundSkills"), list) and parsed["boundSkills"]:
        data["boundSkills"] = list(
            dict.fromkeys(
                [str(x) for x in parsed["boundSkills"]] + list(baseline.boundSkills)
            )
        )[:40]
    if isinstance(parsed.get("defectCodeMatches"), list) and parsed["defectCodeMatches"]:
        # Prefer SDK matches when present; keep baseline for ids SDK omitted.
        by_id = {m["defectId"]: m for m in data.get("defectCodeMatches") or []}
        for item in parsed["defectCodeMatches"]:
            if not isinstance(item, dict) or not item.get("defectId"):
                continue
            by_id[str(item["defectId"])] = item
        data["defectCodeMatches"] = list(by_id.values())
    # Drop hallucinated paths (SDK or merge).
    from bugfix_platform.agents.cartographer.match import filter_existing_candidates
    from bugfix_contracts.code_knowledge import DefectCodeMatch

    parsed_matches = []
    for item in data.get("defectCodeMatches") or []:
        if not isinstance(item, dict):
            continue
        try:
            parsed_matches.append(DefectCodeMatch.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    data["defectCodeMatches"] = [
        m.model_dump()
        for m in filter_existing_candidates(baseline.workDir, parsed_matches)
    ]
    if isinstance(parsed.get("partial"), bool):
        data["partial"] = parsed["partial"]
    else:
        matches = data.get("defectCodeMatches") or []
        data["partial"] = data.get("cartographyProfile") == "unknown" or all(
            not (m.get("candidates") or []) for m in matches
        )
    # Provenance breadcrumb in architecture summary.
    arch = dict(data.get("architecture") or {})
    summary = arch.get("summary") or ""
    if "cartography=sdk" not in summary:
        arch["summary"] = f"{summary}; cartography=sdk" if summary else "cartography=sdk"
    data["architecture"] = arch
    return data


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
        "route modules in one SPA — list them into architecture.modules. (3) greyed-out / "
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
Your job is to thicken the architecture map and improve WEAK/EMPTY path matches.
Agent-3 follows imports and names the fix locus. You do not.

Tools: Read, Glob, Grep, and Bash. Bash is for READ-ONLY exploration only
(e.g. rg/find/git log|blame|grep|show, ls, cat/head/sed -n). NEVER mutate the repo:
no edit/write tools, no git write, no install, no network, no rm/chmod.

cartographyProfile is CALLER-SUPPLIED. Do not reclassify the repo.

How to work:
1) Follow the profile reading playbook, then CLAUDE.md / overlay skills.
   Overlay skills have HIGHEST PRIORITY over package SOP on read order, layout, aliases.
2) Thicken architecture (entryPoints, route/business modules, runtime shape).
   Read catalog files; do not walk the whole repo.
3) Improve ONLY the weak/empty tickets listed in the user prompt. Cap 3 real paths
   per ticket. candidate.why = why the path resembles the title/module — not a root
   cause, not a call-flow. Do not follow imports/callers per ticket.
4) Leave a turn to emit JSON. Incomplete is OK; set partial=true.

Return one JSON object (optionally in a ```json fence) with any of:
secondaryHints, techStack{languages,frameworks,notes},
architecture{summary,entryPoints,modules[{id,path,role,shared,notes}]},
conventions{fromClaudeMd,fromRules}, boundSkills,
defectCodeMatches[{defectId,candidates[{repoPath,path,symbol,why,source}],confidence}],
partial.
Do not change cartographyProfile.
candidate source must be one of: codegraph, grep, heuristic, claude_md.
"""


def _build_prompt(req: CartographyRequest) -> str:
    entries = list(req.baseline.architecture.entryPoints)
    by_id = {m.defectId: m for m in req.baseline.defectCodeMatches}
    weak_tickets = []
    weak_matches = []
    for t in req.defect_batch.tickets:
        if t.pool not in ("strict", "locatable_only", "needs_info"):
            continue
        match = by_id.get(t.defectId)
        if match is not None and not is_weak_match(match, entries):
            continue
        weak_tickets.append(
            {
                "defectId": t.defectId,
                "title": t.title,
                "pool": t.pool,
                "testModule": t.testModule,
                "titleTag": t.titleTag,
                "intent": t.intent,
            }
        )
        if match is not None:
            weak_matches.append(match.model_dump())
        if len(weak_tickets) >= MAX_WEAK_PROMPT_TICKETS:
            break
    baseline = {
        "cartographyProfile": req.baseline.cartographyProfile,
        "secondaryHints": req.baseline.secondaryHints,
        "techStack": req.baseline.techStack.model_dump(),
        "architecture": req.baseline.architecture.model_dump(),
        "conventions": req.baseline.conventions.model_dump(),
        "boundSkills": req.baseline.boundSkills,
        "defectCodeMatches": weak_matches,
        "partial": req.baseline.partial,
    }
    playbook = profile_reading_playbook(req.baseline.cartographyProfile)
    return (
        "Thicken architecture from the playbook, then improve ONLY the listed weak "
        "tickets' path candidates (max 3 each). Do not follow imports or name a fix "
        "locus. Return the JSON enrich object before you run out of turns.\n\n"
        f"productLine: {req.defect_batch.productLine}\n"
        f"workDir: {req.work_dir}\n"
        f"cartographyProfile: {req.baseline.cartographyProfile} (caller-supplied; do not change)\n"
        f"readingPlaybook: {playbook}\n"
        f"injectedSkills: {json.dumps([s.name for s in req.injected_skills], ensure_ascii=False)}\n"
        f"matchPoolTickets: {json.dumps(weak_tickets, ensure_ascii=False)}\n"
        f"baseline: {json.dumps(baseline, ensure_ascii=False)}\n"
    )
