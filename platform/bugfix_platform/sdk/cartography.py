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

# 提示词里带给模型的票数上限。Agent-2 以 SDK 为准，票给全比省 token 重要；
# 这个数只防提示词爆炸，不参与匹配、不参与产物统计。
MAX_PROMPT_TICKETS = 80

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
    - Env empty / ``0`` / ``none`` / ``unlimited`` → unlimited (default)
    - Env positive int → that value
    """
    if explicit is not None:
        return None if explicit <= 0 else explicit
    raw = (os.environ.get("BUGFIX_CARTOGRAPHY_MAX_TURNS") or "").strip().lower()
    if raw in ("", "0", "none", "null", "unlimited", "inf", "infinite"):
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
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
    # None → resolve from env (default unlimited). <=0 also means unlimited.
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


def run_claude_cartography(req: CartographyRequest) -> CartographyResult:
    """Claude Agent SDK session: thorough read of workDir to thicken code-knowledge."""
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
    options = ClaudeAgentOptions(
        cwd=req.work_dir,
        system_prompt=system_prompt,
        allowed_tools=list(CARTOGRAPHY_TOOLS),
        disallowed_tools=list(DISALLOWED_TOOLS),
        permission_mode="dontAsk",
        max_turns=max_turns,
        model=model,
        can_use_tool=_can_use_cartography_tool,
    )

    result_text = ""
    structured: Any = None

    async def _run() -> None:
        nonlocal result_text, structured
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    raise RuntimeError(
                        "; ".join(message.errors or []) or message.result or "cartography SDK error"
                    )
                result_text = message.result or ""
                structured = message.structured_output

    try:
        anyio.run(_run)
    except Exception as err:  # noqa: BLE001
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = f"sdk cartography failed: {err}"
        return fallback

    parsed = parse_json_payload(structured if structured is not None else result_text)
    if parsed is None:
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = "sdk returned no parseable JSON cartography"
        return fallback

    try:
        merged = _merge_enrichment(req.baseline, parsed)
        knowledge = validate_code_knowledge(merged)
    except Exception as err:  # noqa: BLE001
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = f"enriched code-knowledge invalid: {err}"
        return fallback

    return CartographyResult(ok=True, knowledge=knowledge, source="sdk")


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
        "Router/{pc,mobile}.js. (2) greyed-out / missing-feature defects: read "
        "Common/service/device.js before views. (3) real bridge is jsWebControl, not a "
        "folder named bridge. (4) do not look for vue.app.js modules; business dirs are "
        "route modules in one SPA. (5) index.asp is host, not architecture."
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
Your job is to thoroughly read the target workDir so Agent-3 can fix defects with LESS re-exploration token cost.

Tools: Read, Glob, Grep, and Bash. Bash is for READ-ONLY exploration only
(e.g. rg/find/git log|blame|grep|show, ls, cat/head/sed -n). NEVER mutate the repo:
no edit/write tools, no git write, no install, no network, no rm/chmod.

cartographyProfile is CALLER-SUPPLIED. Do not reclassify the repo.

How to work (be thorough, then stop when grounded):
1) Follow the profile reading playbook in the user prompt, then CLAUDE.md / overlay skills.
   Repo-specific injected skills have HIGHEST PRIORITY over package SOP: follow THEIR
   read order, test/src layout, module aliases, and naming on any conflict.
2) For EACH match-pool ticket: open baseline candidate files, follow imports/callers
   with Grep/Bash rg until you can name the likely fix locus and a short call-flow note.
   Stay inside the module / process / PC-mobile fork the architecture map already named.
3) Prefer improving weak/empty matches; do not invent paths. Cap candidates at 3 per ticket.
   Injected skills never lift these caps or let you match outside
   strict/locatable_only/needs_info.
4) Write architecture.summary rich enough that Agent-3 need not re-map the repo:
   include runtime shape, key modules, and per-hotspot call flow in plain language.

Return one JSON object (optionally in a ```json fence) with any of:
secondaryHints, techStack{languages,frameworks,notes},
architecture{summary,entryPoints,modules[{id,path,role,shared,notes}]},
conventions{fromClaudeMd,fromRules}, boundSkills,
defectCodeMatches[{defectId,candidates[{repoPath,path,symbol,why,source}],confidence}],
partial.
Do not change cartographyProfile.
candidate source must be one of: codegraph, grep, heuristic, claude_md.
In each candidate.why, cite the symbol/call edge you actually observed.
"""


def _build_prompt(req: CartographyRequest) -> str:
    match_pool = [
        {
            "defectId": t.defectId,
            "title": t.title,
            "pool": t.pool,
            "testModule": t.testModule,
            "titleTag": t.titleTag,
            "intent": t.intent,
        }
        for t in req.defect_batch.tickets
        if t.pool in ("strict", "locatable_only", "needs_info")
    ][:MAX_PROMPT_TICKETS]
    baseline = {
        "cartographyProfile": req.baseline.cartographyProfile,
        "secondaryHints": req.baseline.secondaryHints,
        "techStack": req.baseline.techStack.model_dump(),
        "architecture": req.baseline.architecture.model_dump(),
        "conventions": req.baseline.conventions.model_dump(),
        "boundSkills": req.baseline.boundSkills,
        "defectCodeMatches": [
            m.model_dump() for m in req.baseline.defectCodeMatches
        ][:MAX_PROMPT_TICKETS],
        "partial": req.baseline.partial,
    }
    playbook = profile_reading_playbook(req.baseline.cartographyProfile)
    return (
        "Thoroughly read this workDir and enrich the code-knowledge baseline so Agent-3 "
        "can fix tickets without rediscovering architecture. Return the JSON enrich object.\n\n"
        f"productLine: {req.defect_batch.productLine}\n"
        f"workDir: {req.work_dir}\n"
        f"cartographyProfile: {req.baseline.cartographyProfile} (caller-supplied; do not change)\n"
        f"readingPlaybook: {playbook}\n"
        f"injectedSkills: {json.dumps([s.name for s in req.injected_skills], ensure_ascii=False)}\n"
        f"matchPoolTickets: {json.dumps(match_pool, ensure_ascii=False)}\n"
        f"baseline: {json.dumps(baseline, ensure_ascii=False)}\n"
    )
