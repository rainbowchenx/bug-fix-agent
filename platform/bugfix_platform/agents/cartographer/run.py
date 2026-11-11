from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from bugfix_platform.agents.cartographer.architecture import map_architecture
from bugfix_platform.agents.cartographer.detect import (
    detect_cartography_profile,
    discover_repo_roots,
    normalize_cartography_profile,
    read_conventions,
)
from bugfix_platform.agents.cartographer.match import (
    filter_existing_candidates,
    match_tickets,
    ticket_variant,
)
from bugfix_contracts import (
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_code_knowledge,
)
from bugfix_contracts.code_knowledge import Architecture, CartographyProfile, SpecAtlas, SpecEntry
from bugfix_platform.sdk.cartography import (
    CartographyRequest,
    CartographyRunner,
    cartography_mode_from_env,
    create_cartography_runner,
)
from bugfix_platform.sdk.skill_inject import InjectedSkill, discover_cartography_skills


def run_cartographer(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    cartography_mode: Optional[str] = None,
    extra_skill_dirs: Optional[Sequence[str | Path]] = None,
    cartography_fn: Optional[CartographyRunner] = None,
    cartography_profile: Optional[str] = None,
) -> CodeKnowledge:
    """Agent-2 公开入口：产出供 Agent-3 消费的 ``code-knowledge``。

    管线（禁止跨 Agent import）::

        发现仓根 → 采用调用方 cartographyProfile → 按类型读清单建图
            → 吃图的路径匹配 →（可选）Claude SDK 加厚
            → validate_code_knowledge

    软匹配只是起点提示；Agent-3 可改写定位结论。仓型**不探测**：由
    ``cartography_profile`` 输入；缺省为 ``unknown``。

    Args:
        work_dir: 目标代码根（其下可有多个仓）。
        defect_batch: 已通过 ``validate_defect_batch`` 的批次。
        cartography_mode: ``heuristic`` / ``sdk``；``None`` 时看环境变量。
        extra_skill_dirs: 用户注入的 overlay skill 根目录。与仓内
            ``.claude/skills``、``workDir/.bugfix/skills``、
            ``BUGFIX_SKILLS_DIR`` 合并；同名后者覆盖。加载
            ``cartography`` / ``bugfix``，以及 ``.bugfix`` / 显式目录里未写
            profiles 的 skill。
        cartography_fn: 可注入的 ``CartographyRunner``（测试用）。
        cartography_profile: 调用方给定的仓型
            ``electron_node`` / ``micro_frontend`` / ``device_web`` /
            ``unknown``。不传则 ``unknown``，不猜测。

    Returns:
        通过 ``validate_code_knowledge`` 的 ``CodeKnowledge``。
    """
    work_dir = str(work_dir)
    profile: CartographyProfile = normalize_cartography_profile(cartography_profile)
    # 1) 扫描目标 workDir 结构（支持多根 monorepo）。
    repo_roots = discover_repo_roots(work_dir)
    _ignored, hints, tech = detect_cartography_profile(work_dir, repo_roots)
    if profile != "unknown":
        hints = [f"caller:{profile}", *hints]
        tech = dict(tech)
        tech["notes"] = f"profile={profile} (caller-supplied)"
    conventions = read_conventions(work_dir, repo_roots)
    injected = discover_cartography_skills(work_dir, repo_roots, extra_skill_dirs)
    bound_skills, atlas_entries = _bind_injected_skills(
        work_dir, conventions, injected
    )
    mapped = map_architecture(work_dir, repo_roots, profile)
    architecture = Architecture(
        summary=mapped.summary,
        entryPoints=mapped.entry_points,
        modules=mapped.modules,
    )

    # 2) 对匹配池票做软定位（strict / locatable_only / needs_info）。
    match_list = [t for t in defect_batch.tickets if is_match_pool(t.pool)]
    code_graph = bool(conventions["codeGraph"])
    defect_code_matches = filter_existing_candidates(
        work_dir,
        match_tickets(
            work_dir,
            repo_roots,
            match_list,
            code_graph=code_graph,
            profile=profile,
            architecture=architecture,
            bindings=mapped.bindings,
        ),
        code_graph=code_graph,
        profile=profile,
        architecture=architecture,
        variant_by_id={t.defectId: ticket_variant(t) for t in match_list},
    )

    partial = profile == "unknown" or all(len(m.candidates) == 0 for m in defect_code_matches)

    atlas = SpecAtlas(
        frameworkId=conventions["frameworkId"],
        entries=atlas_entries,
        bindings=mapped.bindings,
    )
    arch_summary = (
        mapped.summary
        if profile == "unknown"
        else f"{mapped.summary} across {len(repo_roots)} repo root(s)"
    )
    baseline = validate_code_knowledge(
        {
            "schemaVersion": CODE_KNOWLEDGE_SCHEMA_VERSION,
            "productLine": defect_batch.productLine,
            "workDir": work_dir,
            "partial": partial,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "repoRoots": [r.model_dump() for r in repo_roots],
            "cartographyProfile": profile,
            "secondaryHints": hints,
            "techStack": tech,
            "architecture": {
                "summary": arch_summary,
                "entryPoints": architecture.entryPoints,
                "modules": [m.model_dump() for m in architecture.modules],
            },
            "conventions": {
                "fromClaudeMd": conventions["fromClaudeMd"][:30],
                "fromRules": conventions["fromRules"],
            },
            "boundSkills": bound_skills,
            "specAtlas": atlas.model_dump(),
            "capabilities": {
                "codeGraph": code_graph,
                "runtimeVerify": False,
            },
            "defectCodeMatches": [m.model_dump() for m in defect_code_matches],
        }
    )

    # 3) 可选 LLM 加厚（无 key / SDK 失败时回退 heuristic）。
    runner = cartography_fn or create_cartography_runner(
        cartography_mode_from_env(cartography_mode)
    )
    result = runner(
        CartographyRequest(
            work_dir=work_dir,
            defect_batch=defect_batch,
            baseline=baseline,
            injected_skills=tuple(injected),
        )
    )
    # 有没真的调用 LLM，必须能从产物读出来：否则 heuristic 与
    # sdk_fallback（缺 key / 缺 SDK / 输出不可解析）在 JSON 上完全同形。
    print(_enrich_line(result.source, result.detail), file=sys.stderr)
    return _with_enrich_hint(result.knowledge, result.source, result.detail)


def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _enrich_line(source: str, detail: str | None) -> str:
    """一行诊断，走 stderr——stdout 要留给 CLI 的 JSON 结果。"""
    reason = _one_line(detail)
    return f"[agent2] enrich={source}" + (f"; {reason[:200]}" if reason else "")


def _with_enrich_hint(
    knowledge: CodeKnowledge, source: str, detail: str | None
) -> CodeKnowledge:
    """把增强来源写进 ``secondaryHints``（重复调用只保留最新一条）。"""
    note = f"enrich={source}"
    reason = _one_line(detail)
    if reason:
        note = f"{note}; {reason[:200]}"
    data = knowledge.model_dump()
    hints = [
        h for h in (data.get("secondaryHints") or []) if not str(h).startswith("enrich=")
    ]
    hints.append(note)
    data["secondaryHints"] = hints
    return validate_code_knowledge(data)


def _bind_injected_skills(
    work_dir: str,
    conventions: dict,
    injected: Sequence[InjectedSkill],
) -> tuple[list[str], list[SpecEntry]]:
    """把 cartography skill 写入 ``boundSkills`` / ``specAtlas``。

    包内置 skill 只记名字；仓内 / ``.bugfix`` / 显式目录记路径，供 Agent-3 看见。
    """
    bound = list(dict.fromkeys(s.name for s in injected))[:40]
    entries = list(conventions.get("entries") or [])
    seen = {e.path for e in entries}
    root = Path(work_dir)
    for skill in injected:
        if skill.source == "package":
            continue
        try:
            rel = str(skill.skill_md.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(skill.skill_md)
        if rel in seen:
            continue
        seen.add(rel)
        source = "claude_dir" if skill.source == "claude_dir" else "explicit"
        entries.append(SpecEntry(path=rel, kind="skill", source=source))
    return bound, entries
