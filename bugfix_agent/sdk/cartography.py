from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from bugfix_agent.contracts import CodeKnowledge, DefectBatch, validate_code_knowledge
from bugfix_agent.sdk.parse import parse_json_payload
from bugfix_agent.sdk.skills import skills_system_addon

CartographyMode = Literal["heuristic", "sdk"]

CARTOGRAPHY_TOOLS = ["Read", "Glob", "Grep"]
DISALLOWED_TOOLS = ["Edit", "Write", "Bash", "NotebookEdit", "MultiEdit"]


@dataclass
class CartographyRequest:
    work_dir: str
    defect_batch: DefectBatch
    baseline: CodeKnowledge
    """Heuristic detect/match result to enrich."""
    max_turns: int = 16
    model: Optional[str] = None


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
    if os.environ.get("ANTHROPIC_API_KEY"):
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


def run_claude_cartography(req: CartographyRequest) -> CartographyResult:
    """Read-only Claude Agent SDK session to thicken architecture + matches."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        fallback = heuristic_cartography(req)
        fallback.source = "sdk_fallback"
        fallback.detail = "ANTHROPIC_API_KEY missing; fell back to heuristic"
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
    system_prompt = _SYSTEM_PROMPT + skills_system_addon(
        (
            "monorepo-workspace",
            "electron-process-boundary",
            "hierarchical-localization",
        )
    )
    options = ClaudeAgentOptions(
        cwd=req.work_dir,
        system_prompt=system_prompt,
        allowed_tools=list(CARTOGRAPHY_TOOLS),
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
    if parsed.get("cartographyProfile") in (
        "electron_node",
        "micro_frontend",
        "device_web",
        "unknown",
    ):
        data["cartographyProfile"] = parsed["cartographyProfile"]
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
        data["boundSkills"] = [str(x) for x in parsed["boundSkills"]][:40]
    if isinstance(parsed.get("defectCodeMatches"), list) and parsed["defectCodeMatches"]:
        # Prefer SDK matches when present; keep baseline for ids SDK omitted.
        by_id = {m["defectId"]: m for m in data.get("defectCodeMatches") or []}
        for item in parsed["defectCodeMatches"]:
            if not isinstance(item, dict) or not item.get("defectId"):
                continue
            by_id[str(item["defectId"])] = item
        data["defectCodeMatches"] = list(by_id.values())
    # Drop hallucinated paths (SDK or merge).
    from bugfix_agent.agents.cartographer.match import filter_existing_candidates
    from bugfix_agent.contracts.code_knowledge import DefectCodeMatch

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


_SYSTEM_PROMPT = """You are Agent-2 Code Cartographer.
Use only Read / Glob / Grep. Do NOT edit files or run shell.
Read CLAUDE.md / package manifests / likely entry files. Improve the baseline JSON.
Return one JSON object (optionally in a ```json fence) with any of:
cartographyProfile, secondaryHints, techStack{languages,frameworks,notes},
architecture{summary,entryPoints,modules[{id,path,role,shared,notes}]},
conventions{fromClaudeMd,fromRules}, boundSkills,
defectCodeMatches[{defectId,candidates[{repoPath,path,symbol,why,source}],confidence}],
partial.
cartographyProfile must be one of: electron_node, micro_frontend, device_web, unknown.
candidate source must be one of: codegraph, grep, heuristic, claude_md.
Ground claims in files you read. Prefer improving weak/empty matches over inventing paths.
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
    ][:40]
    baseline = {
        "cartographyProfile": req.baseline.cartographyProfile,
        "secondaryHints": req.baseline.secondaryHints,
        "techStack": req.baseline.techStack.model_dump(),
        "architecture": req.baseline.architecture.model_dump(),
        "conventions": req.baseline.conventions.model_dump(),
        "boundSkills": req.baseline.boundSkills,
        "defectCodeMatches": [m.model_dump() for m in req.baseline.defectCodeMatches][:40],
        "partial": req.baseline.partial,
    }
    return (
        "Enrich this code-knowledge baseline for the workDir. Return the JSON enrich object.\n\n"
        f"productLine: {req.defect_batch.productLine}\n"
        f"workDir: {req.work_dir}\n"
        f"matchPoolTickets: {json.dumps(match_pool, ensure_ascii=False)}\n"
        f"baseline: {json.dumps(baseline, ensure_ascii=False)}\n"
    )
