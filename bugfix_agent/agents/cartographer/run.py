from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bugfix_agent.agents.cartographer.architecture import map_architecture
from bugfix_agent.agents.cartographer.detect import (
    detect_cartography_profile,
    discover_repo_roots,
    read_conventions,
)
from bugfix_agent.agents.cartographer.match import filter_existing_candidates, match_tickets
from bugfix_agent.contracts import (
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_code_knowledge,
)
from bugfix_agent.contracts.code_knowledge import SpecAtlas
from bugfix_agent.sdk.cartography import (
    CartographyRequest,
    CartographyRunner,
    cartography_mode_from_env,
    create_cartography_runner,
)


def run_cartographer(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    cartography_mode: Optional[str] = None,
    cartography_fn: Optional[CartographyRunner] = None,
) -> CodeKnowledge:
    """Agent-2 公开入口：产出供 Agent-3 消费的 ``code-knowledge``。

    管线（禁止跨 Agent import）::

        发现仓根 → 探测 profile/技术栈 → 形态化架构图 → 启发式路径匹配
            →（可选）Claude SDK 加厚 → validate_code_knowledge

    软匹配只是起点提示；Agent-3 可改写定位结论。
    """
    work_dir = str(work_dir)
    # 1) 扫描目标 workDir 结构（支持多根 monorepo）。
    repo_roots = discover_repo_roots(work_dir)
    profile, hints, tech = detect_cartography_profile(work_dir, repo_roots)
    conventions = read_conventions(work_dir, repo_roots)
    arch_summary, entry_points, modules = map_architecture(work_dir, repo_roots, profile)

    # 2) 对匹配池票做软定位（strict / locatable_only / needs_info）。
    match_list = [t for t in defect_batch.tickets if is_match_pool(t.pool)]
    code_graph = bool(conventions["codeGraph"])
    defect_code_matches = filter_existing_candidates(
        work_dir,
        match_tickets(work_dir, repo_roots, match_list, code_graph=code_graph),
        code_graph=code_graph,
    )

    partial = profile == "unknown" or all(len(m.candidates) == 0 for m in defect_code_matches)

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
                "summary": (
                    arch_summary
                    if profile == "unknown"
                    else f"{arch_summary} across {len(repo_roots)} repo root(s)"
                ),
                "entryPoints": entry_points,
                "modules": [m.model_dump() for m in modules],
            },
            "conventions": {
                "fromClaudeMd": conventions["fromClaudeMd"][:30],
                "fromRules": conventions["fromRules"],
            },
            "boundSkills": conventions["boundSkills"],
            "specAtlas": SpecAtlas(
                frameworkId=conventions["frameworkId"],
                entries=conventions["entries"],
            ).model_dump(),
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
        CartographyRequest(work_dir=work_dir, defect_batch=defect_batch, baseline=baseline)
    )
    return result.knowledge
