"""Sequential investigation groups with explicit coverage and snapshot-bound reuse."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from bugfix_contracts import is_match_pool
from bugfix_contracts.code_knowledge import CodeKnowledge, DefectCodeMatch
from bugfix_platform.workspace_fingerprint import workspace_digest
from bugfix_platform.sdk.cartography import (
    CartographyRequest, CartographyResult, CartographyRunner,
    resolve_cartography_max_turns,
)
from bugfix_platform.agents.cartographer.investigation_store import (
    load_group_progress,
    save_group_progress,
)

INVESTIGATION_PROTOCOL = "investigation-v3"


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


def _identity(req: CartographyRequest) -> dict:
    return {
        "workspace": workspace_digest(Path(req.work_dir)),
        "model": req.model or os.environ.get("ANTHROPIC_MODEL"),
        "skills": [(s.repoId, s.name, hashlib.sha256(s.skill_md.read_bytes()).hexdigest())
                   for s in req.injected_skills],
        "turns": req.max_turns,
        "profile": req.baseline.cartographyProfile,
        "protocol": INVESTIGATION_PROTOCOL,
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


def _aggregate_billing(records: list[dict]) -> dict:
    sdk_rows = [r for r in records if r.get("source") == "sdk"]
    costs = [r.get("cost") for r in sdk_rows]
    turns = [r.get("turns") for r in sdk_rows]
    if sdk_rows and any(c is None for c in costs):
        return {"aggregate": "unknown"}
    payload = {"aggregate": "sum" if sdk_rows else "none"}
    if sdk_rows and all(isinstance(c, (int, float)) for c in costs):
        payload["cost"] = float(sum(costs))
    if sdk_rows and all(isinstance(t, int) for t in turns):
        payload["turns"] = int(sum(turns))
    return payload


def investigate_groups(
    req: CartographyRequest,
    runner: CartographyRunner,
    *,
    group_size: int = 8,
    max_groups: int | None = None,
    cache_dir: str | Path | None = None,
    artifact_dir: str | Path | None = None,
    resume_dir: str | Path | None = None,
    ticket_ids: list[str] | None = None,
) -> CartographyResult:
    tickets = {t.defectId: t for t in req.defect_batch.tickets if is_match_pool(t.pool)}
    selected = list(dict.fromkeys(ticket_ids)) if ticket_ids is not None else list(tickets)
    selected = [i for i in selected if i in tickets]
    groups = plan_groups(selected, group_size)
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    artifacts = Path(artifact_dir) if artifact_dir else (Path(resume_dir) if resume_dir else None)
    merged = {m.defectId: m for m in req.baseline.defectCodeMatches}
    reset_ids = set(selected) if ticket_ids is not None else set(tickets)
    for defect_id in reset_ids:
        current = merged.get(defect_id)
        if current is None:
            merged[defect_id] = DefectCodeMatch(
                defectId=defect_id, investigationStatus="not_investigated",
            )
        else:
            merged[defect_id] = current.model_copy(update={"investigationStatus": "not_investigated"})
    for defect_id in tickets:
        merged.setdefault(defect_id, DefectCodeMatch(
            defectId=defect_id, investigationStatus="not_investigated",
        ))
    knowledge = req.baseline
    records: list[dict] = []
    skill_reads: set[str] = set()
    incomplete = False
    started = time.monotonic()
    seconds = float(os.environ.get("BUGFIX_INVESTIGATION_TIMEOUT_SECONDS", "1800"))
    identity = _identity(req)
    journal = load_group_progress(resume_dir) if resume_dir else None
    journal_by_key: dict[str, dict] = {}
    identity_json = json.dumps(identity, sort_keys=True, default=str)
    identity_ok = isinstance(journal, dict) and json.dumps(journal.get("identity") or {}, sort_keys=True, default=str) == identity_json
    if identity_ok:
        for item in list(journal.get("groups") or []):
            if not isinstance(item, dict):
                continue
            cache_key = item.get("cacheKey")
            if isinstance(cache_key, str) and cache_key:
                journal_by_key[cache_key] = item
        for item in list(journal.get("groups") or []):
            ids = [str(x) for x in (item.get("ids") or [])]
            if not ids or any(i not in tickets for i in ids):
                continue
            current_tickets = [tickets[i] for i in ids]
            expected_key = hashlib.sha256(json.dumps({
                "identity": identity, "tickets": [t.model_dump() for t in current_tickets],
            }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if expected_key != item.get("cacheKey"):
                continue
            for raw in item.get("matches") or []:
                try:
                    restored_match = DefectCodeMatch.model_validate(raw)
                except (ValueError, TypeError):
                    continue
                if restored_match.defectId in reset_ids:
                    continue
                if restored_match.defectId in ids:
                    merged[restored_match.defectId] = restored_match
    launched = 0
    stop_reason = "completed"

    def _group_payload(record: dict) -> dict:
        ids = list(record.get("ids") or [])
        return {
            "ids": ids,
            "cacheKey": record.get("cacheKey"),
            "status": record.get("status"),
            "partial": bool(record.get("partial") or record.get("status") != "complete"),
            "stopReason": record.get("stopReason"),
            "source": record.get("source"),
            "detail": record.get("detail"),
            "turns": record.get("turns"),
            "cost": record.get("cost"),
            "matches": [merged[i].model_dump() for i in ids if i in merged],
        }

    def _flush_journal() -> None:
        if artifacts is None:
            return
        by_key: dict[str, dict] = {}
        order: list[str] = []
        if identity_ok:
            for item in list((journal or {}).get("groups") or []):
                cache_key = item.get("cacheKey") if isinstance(item, dict) else None
                if isinstance(cache_key, str) and cache_key:
                    by_key[cache_key] = item
                    order.append(cache_key)
        for record in records:
            cache_key = record.get("cacheKey")
            payload = _group_payload(record)
            if isinstance(cache_key, str) and cache_key:
                if cache_key not in by_key:
                    order.append(cache_key)
                by_key[cache_key] = payload
            else:
                order.append(f"anon-{len(order)}")
                by_key[order[-1]] = payload
        save_group_progress(artifacts, {
            "identity": identity,
            "stopReason": stop_reason,
            "billing": _aggregate_billing(records),
            "groups": [by_key[key] for key in order if key in by_key],
        })
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
        journal_hit = journal_by_key.get(key)
        if result is None and journal_hit and journal_hit.get("matches"):
            try:
                restored = [
                    DefectCodeMatch.model_validate(item) for item in journal_hit["matches"]
                ]
                for match in restored:
                    merged[match.defectId] = match
                group_partial = bool(journal_hit.get("partial")) or journal_hit.get("status") != "complete"
                cached_k = knowledge.model_copy(update={
                    "defectCodeMatches": restored, "partial": group_partial,
                })
                if (
                    journal_hit.get("status") == "complete"
                    and not journal_hit.get("partial")
                    and _complete(cached_k, ids)
                ):
                    result = CartographyResult(True, cached_k, "sdk", "resumed complete group")
            except (ValueError, TypeError):
                result = None
        group_base = knowledge.model_copy(update={
            "defectCodeMatches": [merged[i] for i in ids],
        })
        try:
            if result is None:
                exhausted = max_groups is not None and launched >= max_groups
                timed_out = time.monotonic() - started >= seconds
                if exhausted or timed_out:
                    stop_reason = "timeout" if timed_out else "budget_exhausted"
                    break
                launched += 1
                group_id = f"g{n:03d}-{key[:8]}"
                call_id = uuid4().hex[:12]
                result = runner(replace(
                    req,
                    defect_batch=batch,
                    baseline=group_base,
                    investigation_only=n > 0,
                    artifact_dir=artifacts,
                    group_id=group_id,
                    call_id=call_id,
                ))
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
            group_partial = bool(result.knowledge.partial)
            group_status = "complete" if _complete(
                knowledge.model_copy(update={
                    "defectCodeMatches": [merged[i] for i in ids],
                    "partial": group_partial,
                }),
                ids,
            ) else "partial"
            record = {
                "ids": ids, "source": result.source, "detail": result.detail, "cacheKey": key,
                "stage": "map_and_investigation" if n == 0 else "investigation",
                "maxTurns": resolve_cartography_max_turns(req.max_turns, ticket_count=len(ids)),
                "stopReason": "completed" if group_status == "complete" else "partial",
                "status": group_status,
                "partial": group_partial or group_status != "complete",
                "turns": result.turns,
                "cost": result.cost,
            }
            records.append(record)
            _flush_journal()
        except Exception as err:
            stop_reason = "failed"
            for defect_id in ids:
                merged[defect_id] = merged[defect_id].model_copy(update={"investigationStatus": "failed"})
            records.append({
                "ids": ids, "source": "failed", "detail": str(err), "cacheKey": key,
                "stopReason": "failed", "status": "failed",
                "turns": None, "cost": None,
            })
            _flush_journal()
    partial = incomplete or any(
        m.investigationStatus in {"not_investigated", "failed", "partial"}
        for m in merged.values()
    )
    if stop_reason == "completed" and partial:
        stop_reason = "partial"
    _flush_journal()
    knowledge = knowledge.model_copy(update={
        "defectCodeMatches": list(merged.values()), "partial": partial,
        "investigationRuns": records,
    })
    sources = {r["source"] for r in records}
    source = "sdk" if "sdk" in sources else "sdk_fallback" if sources else "heuristic"
    billing = _aggregate_billing(records)
    detail = "; ".join(str(r["detail"]) for r in records if r.get("detail"))
    detail += (
        f"; groups={len(records)}/{len(groups)}; elapsed={time.monotonic()-started:.2f}s; "
        f"partial={partial}; stopReason={stop_reason}; billing={billing.get('aggregate')}"
    )
    return CartographyResult(True, knowledge, source, detail, sorted(skill_reads))
