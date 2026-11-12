from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, get_args

from bugfix_contracts import CodeKnowledge, DefectBatch, validate_code_knowledge
from bugfix_contracts.code_knowledge import DefectCodeMatch, MatchGap
from bugfix_platform.sdk.parse import parse_json_payload
from bugfix_platform.sdk.credentials import has_credentials
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
# 地图/playbook 开销 + 每张进 prompt 票的浅配额。
# 覆盖率取决于进 prompt 的票；配额故意偏浅（宁可全过一遍，也不单票深挖）。
DEFAULT_CARTOGRAPHY_BASE_TURNS = 6
DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET = 2
# ``gap`` 是机器枚举（空候选的原因码），不是给模型写解释的地方。
_ALLOWED_GAPS = frozenset(get_args(MatchGap))
# 候选集完全相同的票达到这个数，说明打分并列、路径 token 没区分度（假 medium）。
SHARED_SIGNATURE_MIN_TICKETS = 3
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
    """Claude Agent SDK session: thicken architecture + shallow-pass match-pool tickets."""
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
        drop_stats: dict[str, int] = {}
        try:
            merged = _merge_enrichment(
                req.baseline,
                parsed,
                tickets=req.defect_batch.tickets,
                stats=drop_stats,
            )
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
        detail = _with_drop_detail(billing, drop_stats)
        return CartographyResult(
            ok=True, knowledge=knowledge, source="sdk", detail=detail or None
        )

    if budget_stop:
        return _sdk_keep_baseline(req, billing)

    fallback = heuristic_cartography(req)
    fallback.source = "sdk_fallback"
    fallback.detail = "sdk returned no parseable JSON cartography"
    return fallback


def _with_drop_detail(
    billing: str | None, stats: dict[str, int] | None
) -> str | None:
    """把被丢弃的候选数并进报账行。

    SDK 报的候选被静态闸（不存在 / 空壳 / 假符号）杀光时不报账，产物上只剩
    ``enrich=sdk``，看不出模型答了却被扔掉——peitao 那次 6 个候选就是这么消失的。
    """
    if not stats:
        return billing
    dropped = "/".join(f"{k}:{v}" for k, v in sorted(stats.items()))
    return f"{billing}; dropped={dropped}" if billing else f"dropped={dropped}"


def _merge_enrichment(
    baseline: CodeKnowledge,
    parsed: dict[str, Any],
    tickets: list[Any] | None = None,
    *,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
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
            arch["modules"] = _merge_modules(arch.get("modules") or [], incoming["modules"])
        data["architecture"] = arch
    if isinstance(parsed.get("conventions"), dict):
        conv = dict(data.get("conventions") or {})
        incoming = parsed["conventions"]
        if isinstance(incoming.get("fromRules"), list) and incoming["fromRules"]:
            conv["fromRules"] = [str(x) for x in incoming["fromRules"]][:40]
        data["conventions"] = conv
    if isinstance(parsed.get("boundSkills"), list) and parsed["boundSkills"]:
        data["boundSkills"] = list(
            dict.fromkeys(
                [str(x) for x in parsed["boundSkills"]] + list(baseline.boundSkills)
            )
        )[:40]
    sdk_ids: set[str] = set()
    if isinstance(parsed.get("defectCodeMatches"), list) and parsed["defectCodeMatches"]:
        # Prefer SDK matches when present; keep baseline for ids SDK omitted.
        by_id = {m["defectId"]: m for m in data.get("defectCodeMatches") or []}
        for item in parsed["defectCodeMatches"]:
            if not isinstance(item, dict) or not item.get("defectId"):
                continue
            did = str(item["defectId"])
            sdk_ids.add(did)
            cleaned = _coerce_sdk_match(dict(item), stats)
            if cleaned is None:
                # 覆盖之前先校验：以前一条不合 schema 的条目会先把 baseline 那条顶掉，
                # 再在下面的解析循环里被静默丢弃 —— 模型答对的票在产物里直接消失（led）。
                _bump(stats, "invalid_match")
                continue
            # 模型只回 defectId/candidates/confidence；标的身份字段从 baseline 继承，
            # 否则被覆盖的票在产物里标题变成 null（下游只能看到一串 BGCM 号）。
            orig = by_id.get(did) or {}
            for key in ("title", "clusterId"):
                if not cleaned.get(key) and orig.get(key):
                    cleaned[key] = orig[key]
            by_id[did] = cleaned
        data["defectCodeMatches"] = list(by_id.values())
    # Drop hallucinated paths (SDK or merge). Empty SDK tickets fall back to baseline.
    from bugfix_platform.agents.cartographer.match import (
        filter_existing_candidates,
        ticket_variant,
    )

    parsed_matches = []
    for item in data.get("defectCodeMatches") or []:
        if not isinstance(item, dict):
            continue
        try:
            parsed_matches.append(DefectCodeMatch.model_validate(item))
        except Exception:  # noqa: BLE001
            _bump(stats, "invalid_match")
            continue
    baseline_by_id = {m.defectId: m for m in baseline.defectCodeMatches}
    variant_by_id = {
        t.defectId: ticket_variant(t) for t in (tickets or []) if getattr(t, "defectId", None)
    }
    merged_matches: list[dict[str, Any]] = []
    for match in filter_existing_candidates(
        baseline.workDir,
        parsed_matches,
        profile=baseline.cartographyProfile,
        architecture=baseline.architecture,
        variant_by_id=variant_by_id or None,
        stats=stats,
    ):
        if match.defectId in sdk_ids:
            if not match.candidates:
                orig = baseline_by_id.get(match.defectId)
                merged_matches.append((orig or match).model_dump())
                continue
            if match.confidence == "high":
                match = match.model_copy(update={"confidence": "medium"})
        merged_matches.append(match.model_dump())
    data["defectCodeMatches"] = merged_matches
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


def _bump(stats: dict[str, int] | None, key: str) -> None:
    if stats is not None:
        stats[key] = stats.get(key, 0) + 1


def _coerce_sdk_match(
    item: dict[str, Any], stats: dict[str, int] | None
) -> dict[str, Any] | None:
    """把模型条目收成契约允许的形状；实在不可用才返回 ``None``。

    ``gap`` 是空候选的原因码（枚举 ``no_path_token_overlap``）。提示词里给出的
    baseline 示例带着 ``"gap": null``，模型会照着补一句人话解释 —— 整条
    ``DefectCodeMatch`` 就校验失败。这一个字段不值一张票，只丢掉它。
    """
    gap = item.get("gap")
    if gap is not None and gap not in _ALLOWED_GAPS:
        item.pop("gap", None)
        _bump(stats, "gap_coerced")
    try:
        DefectCodeMatch.model_validate(item)
    except Exception:  # noqa: BLE001
        return None
    return item


def _merge_modules(
    baseline: list[Any], incoming: list[Any]
) -> list[dict[str, Any]]:
    """按 ``id`` 合并模块表：规则算出的结构节点不允许被模型的目录汇总盖掉。

    整段替换时实测会把 11 个 ``controller`` 域与 11 个 ``ipc:<Prefix>`` 映射
    节点换成一句散文式的 ``controller-devices``（led 轮），而这恰好是
    electron 仓定位的主索引。模型的增量价值在 ``notes``/``role``，同名覆盖
    这些字段即可；它新提出的模块追加在后面。
    """
    out: list[dict[str, Any]] = [dict(m) for m in baseline if isinstance(m, dict)]
    index = {str(m.get("id")): i for i, m in enumerate(out)}
    for item in incoming:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        mid = str(item["id"])
        if mid in index:
            merged = dict(out[index[mid]])
            merged.update({k: v for k, v in item.items() if v is not None and v != ""})
            out[index[mid]] = merged
        else:
            index[mid] = len(out)
            out.append(dict(item))
    return out


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

Tools: Read, Glob, Grep, and Bash. Bash is for READ-ONLY exploration only
(e.g. rg/find/git log|blame|grep|show, ls, cat/head/sed -n). NEVER mutate the repo:
no edit/write tools, no git write, no install, no network, no rm/chmod.

cartographyProfile is CALLER-SUPPLIED. Do not reclassify the repo.

How to work:
1) Follow the profile reading playbook, then CLAUDE.md / overlay skills.
   Overlay skills have HIGHEST PRIORITY over package SOP on read order, layout, aliases.
2) Thicken architecture (entryPoints, route/business modules, runtime shape).
   Read catalog files; do not walk the whole repo.
3) Cover EVERY ticket in matchPoolTickets — shallow, not deep. Cap 3 real paths
   per ticket; 0 is valid — do not pad. Empty is better than a wrong path or
   sibling stubs (mixin.js / isapi.js with no logic).
   Heuristic medium/high candidates are UNVERIFIED path-token hits: confirm with
   a quick Grep/Read, replace if wrong, or clear them. Do not copy them blindly.
   candidate.why = why the path resembles the title/module — not a root cause,
   not a call-flow. Do not follow imports/callers per ticket.
   Route tables, shells, hosts and entryPoints are not fix loci. If the ticket
   names web/PC, do not return /mobile/ or /h5/ exclusive files.
4) Leave a turn to emit JSON. Incomplete is OK; set partial=true.

Return one JSON object (optionally in a ```json fence) with any of:
secondaryHints, techStack{languages,frameworks,notes},
architecture{summary,entryPoints,modules[{id,path,role,shared,notes}]},
conventions{fromRules}, boundSkills,
defectCodeMatches[{defectId,candidates[{repoPath,path,symbol,why,source}],confidence}],
partial.
Do not change cartographyProfile. Do not add keys that are not listed above: an
entry that does not fit that shape is dropped before delivery, losing the whole
ticket. ``gap`` is not yours to write.
candidate source must be one of: codegraph, grep, heuristic, claude_md.
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
    budget = cartography_turns_for_tickets(len(pairs))
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
    return (
        "Thicken architecture from the playbook, then shallow-pass EVERY listed "
        "match-pool ticket (max 3 paths each; 0 is valid, do not pad). "
        "heuristicUnverified=true means baseline candidates are untrusted — "
        "confirm, replace, or clear. Catalog files are not loci. Do not follow "
        "imports or name a fix locus. Return the JSON enrich object before you "
        "run out of turns.\n\n"
        f"productLine: {req.defect_batch.productLine}\n"
        f"workDir: {req.work_dir}\n"
        f"cartographyProfile: {req.baseline.cartographyProfile} (caller-supplied; do not change)\n"
        f"readingPlaybook: {playbook}\n"
        f"turnBudget: {budget} "
        f"(base={_env_positive_int('BUGFIX_CARTOGRAPHY_BASE_TURNS', DEFAULT_CARTOGRAPHY_BASE_TURNS)}"
        f" + perTicket={_env_positive_int('BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET', DEFAULT_CARTOGRAPHY_TURNS_PER_TICKET)}"
        f" × promptTickets={len(pairs)})\n"
        f"injectedSkills: {json.dumps([s.name for s in req.injected_skills], ensure_ascii=False)}\n"
        f"matchPoolTickets: {json.dumps(pool_tickets, ensure_ascii=False)}\n"
        f"baseline: {json.dumps(baseline, ensure_ascii=False)}\n"
    )
