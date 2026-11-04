from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bugfix_agent.agents.cartographer.detect import (
    detect_cartography_profile,
    discover_repo_roots,
    read_conventions,
)
from bugfix_agent.agents.cartographer.match import match_tickets
from bugfix_agent.contracts import (
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_code_knowledge,
)
from bugfix_agent.contracts.code_knowledge import ArchModule, SpecAtlas
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
    """Agent-2: heuristic detect/match, then optional SDK enrich (S2b)."""
    work_dir = str(work_dir)
    repo_roots = discover_repo_roots(work_dir)
    profile, hints, tech = detect_cartography_profile(work_dir, repo_roots)
    conventions = read_conventions(work_dir, repo_roots)

    match_list = [t for t in defect_batch.tickets if is_match_pool(t.pool)]
    defect_code_matches = match_tickets(work_dir, repo_roots, match_list)

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
                    "Profile unknown; architecture map deferred"
                    if profile == "unknown"
                    else f"Detected {profile} across {len(repo_roots)} repo root(s)"
                ),
                "entryPoints": [],
                "modules": [
                    ArchModule(id=r.path, path=r.path, role="repo_root").model_dump()
                    for r in repo_roots
                ],
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
                "codeGraph": conventions["codeGraph"],
                "runtimeVerify": False,
            },
            "defectCodeMatches": [m.model_dump() for m in defect_code_matches],
        }
    )

    runner = cartography_fn or create_cartography_runner(
        cartography_mode_from_env(cartography_mode)
    )
    result = runner(
        CartographyRequest(work_dir=work_dir, defect_batch=defect_batch, baseline=baseline)
    )
    return result.knowledge
