"""Sequential investigation groups with explicit coverage and snapshot-bound reuse."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import time

from bugfix_contracts import is_match_pool
from bugfix_contracts.code_knowledge import CodeKnowledge, DefectCodeMatch
from bugfix_platform.workspace_fingerprint import workspace_digest
from bugfix_platform.sdk.cartography import (
    CartographyRequest, CartographyResult, CartographyRunner,
    resolve_cartography_max_turns,
)


def plan_groups(ticket_ids: list[str], group_size: int = 8) -> list[list[str]]:
    if not 1 <= group_size <= 16:
        raise ValueError("group_size must be between 1 and 16")
    ids = list(dict.fromkeys(ticket_ids))
    return [ids[i:i + group_size] for i in range(0, len(ids), group_size)]


def _complete(knowledge: CodeKnowledge, ids: list[str]) -> bool:
    matches = knowledge.defectCodeMatches
    return (
        not knowledge.partial
        and {m.defectId for m in matches} == set(ids)
        and all(m.investigationStatus == "complete" for m in matches)
    )


def investigate_groups(
    req: CartographyRequest,
    runner: CartographyRunner,
    *,
    group_size: int = 8,
    max_groups: int | None = None,
    cache_dir: str | Path | None = None,
) -> CartographyResult:
    tickets = {t.defectId: t for t in req.defect_batch.tickets if is_match_pool(t.pool)}
    groups = plan_groups(list(tickets), group_size)
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    merged = {
        m.defectId: m.model_copy(update={"investigationStatus": "not_investigated"})
        for m in req.baseline.defectCodeMatches
    }
    for defect_id in tickets:
        merged.setdefault(defect_id, DefectCodeMatch(
            defectId=defect_id, investigationStatus="not_investigated",
        ))
    knowledge = req.baseline
    records = []
    skill_reads: set[str] = set()
    incomplete = False
    started = time.monotonic()
    seconds = float(os.environ.get("BUGFIX_INVESTIGATION_TIMEOUT_SECONDS", "1800"))
    identity = {
        "workspace": workspace_digest(Path(req.work_dir)),
        "model": req.model or os.environ.get("ANTHROPIC_MODEL"),
        "skills": [(s.repoId, s.name, hashlib.sha256(s.skill_md.read_bytes()).hexdigest())
                   for s in req.injected_skills],
        "turns": req.max_turns,
        "profile": req.baseline.cartographyProfile,
        "protocol": "investigation-v2",
        "navigation": {
            "architecture": req.baseline.architecture.model_dump(),
            "conventions": req.baseline.conventions.model_dump(),
            "specAtlas": req.baseline.specAtlas.model_dump(),
        },
        "config": {k: os.environ.get(k) for k in (
            "ANTHROPIC_BASE_URL", "BUGFIX_CARTOGRAPHY_MAX_TURNS",
            "BUGFIX_CARTOGRAPHY_BASE_TURNS", "BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET",
            "BUGFIX_MODEL_CONTEXT_WINDOW", "BUGFIX_MODEL_MODALITIES",
        )},
    }
    launched = 0
    for n, ids in enumerate(groups):
        batch = req.defect_batch.model_copy(update={"tickets": [tickets[i] for i in ids]})
        key = hashlib.sha256(json.dumps({
            "identity": identity, "tickets": [t.model_dump() for t in batch.tickets],
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        dest = cache / f"{key}.json" if cache else None
        result = None
        if dest and dest.is_file():
            try:
                cached = CodeKnowledge.model_validate_json(dest.read_text(encoding="utf-8"))
                if _complete(cached, ids):
                    result = CartographyResult(True, cached, "sdk", "cached group")
            except (ValueError, OSError):
                pass  # Invalid cache entries are re-investigated, never promoted.
        group_base = knowledge.model_copy(update={
            "defectCodeMatches": [merged[i] for i in ids],
        })
        try:
            if result is None:
                exhausted = max_groups is not None and launched >= max_groups
                if exhausted or time.monotonic() - started >= seconds:
                    break
                launched += 1
                result = runner(replace(req, defect_batch=batch, baseline=group_base,
                                        investigation_only=n > 0))
            skill_reads.update(result.skill_reads)
            incomplete |= result.knowledge.partial or not result.ok or result.source != "sdk"
            returned = result.knowledge.defectCodeMatches
            if (len({m.defectId for m in returned}) != len(returned)
                    or any(m.defectId not in ids for m in returned)):
                raise ValueError("investigation returned duplicate or out-of-group ticket")
            for match in returned:
                merged[match.defectId] = match
            if result.source == "sdk":
                knowledge = result.knowledge
                if dest and result.ok and _complete(result.knowledge, ids):
                    temporary = dest.with_suffix(".tmp")
                    temporary.write_text(result.knowledge.model_dump_json(), encoding="utf-8")
                    temporary.replace(dest)
            records.append({
                "ids": ids, "source": result.source, "detail": result.detail, "cacheKey": key,
                "stage": "map_and_investigation" if n == 0 else "investigation",
                "maxTurns": resolve_cartography_max_turns(req.max_turns, ticket_count=len(ids)),
            })
        except Exception as err:
            for defect_id in ids:
                merged[defect_id] = merged[defect_id].model_copy(update={"investigationStatus": "failed"})
            records.append({"ids": ids, "source": "failed", "detail": str(err), "cacheKey": key})
    partial = incomplete or any(
        m.investigationStatus in {"not_investigated", "failed", "partial"}
        for m in merged.values()
    )
    knowledge = knowledge.model_copy(update={
        "defectCodeMatches": list(merged.values()), "partial": partial,
        "investigationRuns": records,
    })
    sources = {r["source"] for r in records}
    source = "sdk" if "sdk" in sources else "sdk_fallback" if sources else "heuristic"
    detail = "; ".join(str(r["detail"]) for r in records if r.get("detail"))
    detail += f"; groups={len(records)}/{len(groups)}; elapsed={time.monotonic()-started:.2f}s; partial={partial}"
    return CartographyResult(True, knowledge, source, detail, sorted(skill_reads))
