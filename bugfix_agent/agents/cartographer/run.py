from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
from bugfix_agent.contracts.code_knowledge import ArchModule, SpecAtlas, TechStack


def run_cartographer(*, work_dir: str | Path, defect_batch: DefectBatch) -> CodeKnowledge:
    work_dir = str(work_dir)
    repo_roots = discover_repo_roots(work_dir)
    profile, hints, tech = detect_cartography_profile(work_dir, repo_roots)
    conventions = read_conventions(work_dir, repo_roots)

    match_list = [t for t in defect_batch.tickets if is_match_pool(t.pool)]
    defect_code_matches = match_tickets(work_dir, repo_roots, match_list)

    partial = profile == "unknown" or all(len(m.candidates) == 0 for m in defect_code_matches)

    knowledge = {
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
                ArchModule(id=r.path, path=r.path, role="repo_root").model_dump() for r in repo_roots
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
    return validate_code_knowledge(knowledge)
