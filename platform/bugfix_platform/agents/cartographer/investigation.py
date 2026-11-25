"""Sequential investigation groups with explicit coverage and snapshot-bound reuse."""
from dataclasses import replace
from collections.abc import Iterable
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

INVESTIGATION_PROTOCOL = "investigation-v5"


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
        and all(m.investigationStatus == "complete" and m.storageStatus != "artifact_error" for m in matches)
    )


def _identity(req: CartographyRequest) -> dict:
    from bugfix_platform.sdk.model_env import sdk_env_overrides

    # 平台注入的 OPENAI_* 会映射成 ANTHROPIC_*，缓存 key 必须算上映射结果，
    # 否则换了模型/网关仍会命中旧缓存。
    effective = {**os.environ, **sdk_env_overrides()}
    return {
        "workspace": workspace_digest(Path(req.work_dir)),
        "model": req.model or effective.get("ANTHROPIC_MODEL"),
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
        "config": {k: effective.get(k) for k in (
            "ANTHROPIC_BASE_URL", "BUGFIX_CARTOGRAPHY_MAX_TURNS",
            "BUGFIX_CARTOGRAPHY_BASE_TURNS", "BUGFIX_CARTOGRAPHY_TURNS_PER_TICKET",
            "BUGFIX_MODEL_CONTEXT_WINDOW", "BUGFIX_MODEL_MODALITIES",
        )},
    }


def _aggregate_billing(records: list[dict]) -> dict:
    sdk_rows = [row for row in records if row.get("sdkLaunched")]
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
    ticket_progress = {defect_id: {"state": "pending", "launched": False, "accepted": False}
                       for defect_id in tickets}
    launched_this_run: set[str] = set()
    reused_this_run: set[str] = set()
    unselected_partial_ids: set[str] = set()
    identity_json = json.dumps(identity, sort_keys=True, default=str)
    identity_ok = isinstance(journal, dict) and json.dumps(journal.get("identity") or {}, sort_keys=True, default=str) == identity_json
    if identity_ok:
        for item in list(journal.get("groups") or []):
            if not isinstance(item, dict):
                continue
            cache_key = item.get("cacheKey")
            if isinstance(cache_key, str) and cache_key:
                journal_by_key[cache_key] = item
        for item in journal_by_key.values():
            ids = [str(x) for x in (item.get("ids") or [])]
            if not ids or any(i not in tickets for i in ids):
                continue
            current_tickets = [tickets[i] for i in ids]
            expected_key = hashlib.sha256(json.dumps({
                "identity": identity, "tickets": [t.model_dump() for t in current_tickets],
            }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if expected_key != item.get("cacheKey"):
                continue
            for defect_id, row in (item.get("ticketProgress") or {}).items():
                if defect_id in ids and isinstance(row, dict):
                    state = row.get("state")
                    if state in {"running", "interrupted", "complete", "partial", "failed", "pending"}:
                        ticket_progress[defect_id] = {
                            "state": "interrupted" if state == "running" else state,
                            "launched": row.get("launched") is True,
                            "accepted": row.get("accepted") is True,
                        }
            for raw in item.get("matches") or []:
                try:
                    restored_match = DefectCodeMatch.model_validate(raw)
                except (ValueError, TypeError):
                    continue
                if restored_match.defectId in reset_ids:
                    continue
                if restored_match.defectId in ids:
                    merged[restored_match.defectId] = restored_match
                    if item.get("partial") or item.get("status") != "complete":
                        unselected_partial_ids.add(restored_match.defectId)
                    else:
                        unselected_partial_ids.discard(restored_match.defectId)
    launched = 0
    stop_reason = "completed"
    journal_error: str | None = None

    def _counts(ids: Iterable[str]) -> dict[str, int]:
        rows = [ticket_progress[defect_id] for defect_id in ids]
        return {
            "planned": len(rows),
            "launched": sum(row["launched"] for row in rows),
            "accepted": sum(row["accepted"] for row in rows),
            **{state: sum(row["state"] == state for row in rows)
               for state in ("pending", "running", "interrupted", "complete", "partial", "failed")},
        }

    def _group_payload(record: dict) -> dict:
        ids = list(record.get("ids") or [])
        return {
            "ids": ids,
            "counts": _counts(ids),
            "ticketProgress": {defect_id: ticket_progress[defect_id] for defect_id in ids},
            "callId": record.get("callId"),
            "groupId": record.get("groupId"),
            "sdkLaunched": record.get("sdkLaunched", False),
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

    def _flush_journal(active: dict | None = None) -> bool:
        nonlocal journal_error
        if artifacts is None:
            return True
        by_key: dict[str, dict] = {}
        order: list[str] = []
        if identity_ok:
            for item in list((journal or {}).get("groups") or []):
                cache_key = item.get("cacheKey") if isinstance(item, dict) else None
                if isinstance(cache_key, str) and cache_key:
                    if item.get("status") == "running" and all(i in tickets for i in item.get("ids", [])):
                        item = _group_payload({**item, "status": "interrupted", "stopReason": "interrupted"})
                    by_key[cache_key] = item
                    order.append(cache_key)
        if active is not None:
            indexed = [*records, active]
        else:
            indexed = records
        for record in indexed:
            cache_key = record.get("cacheKey")
            payload = _group_payload(record)
            if isinstance(cache_key, str) and cache_key:
                if cache_key in by_key:
                    order.remove(cache_key)
                order.append(cache_key)
                by_key[cache_key] = payload
            else:
                order.append(f"anon-{len(order)}")
                by_key[order[-1]] = payload
        try:
            save_group_progress(artifacts, {
                "identity": identity,
                "stopReason": "running" if active is not None else stop_reason,
                "counts": _counts(tickets),
                "ticketProgress": ticket_progress,
                "launchedThisRun": len(launched_this_run),
                "reusedThisRun": len(reused_this_run),
                "billing": _aggregate_billing(list(by_key.values())),
                "groups": [by_key[key] for key in order if key in by_key],
            })
        except OSError as err:
            journal_error = str(err)
            return False
        return True
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
        restored_by_id: dict[str, DefectCodeMatch] = {}
        journal_hit = journal_by_key.get(key)
        if result is None and journal_hit and journal_hit.get("matches"):
            try:
                restored = [
                    DefectCodeMatch.model_validate(item) for item in journal_hit["matches"]
                ]
                restored_by_id = {match.defectId: match for match in restored if match.defectId in ids}
                merged.update(restored_by_id)
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
        call_id = None
        group_id = None
        reused = result is not None
        previous_progress = {defect_id: ticket_progress[defect_id] for defect_id in ids}
        try:
            if result is None:
                exhausted = max_groups is not None and launched >= max_groups
                timed_out = time.monotonic() - started >= seconds
                if exhausted or timed_out:
                    stop_reason = "time_budget" if timed_out else "group_budget"
                    incomplete = True
                    # Other groups may still have reusable records without spending budget.
                    continue
                launched += 1
                group_id = f"g{n:03d}-{key[:8]}"
                call_id = uuid4().hex[:12]
                launched_this_run.update(ids)
                for defect_id in ids:
                    ticket_progress[defect_id] = {
                        **previous_progress[defect_id], "state": "running", "launched": True,
                    }
                _flush_journal({"ids": ids, "cacheKey": key, "callId": call_id,
                                "groupId": group_id, "sdkLaunched": True,
                                "status": "running", "stopReason": "running"})
                result = runner(replace(
                    req,
                    defect_batch=batch,
                    baseline=group_base,
                    investigation_only=n > 0,
                    artifact_dir=artifacts,
                    group_id=group_id,
                    call_id=call_id,
                    deadline=started + seconds,
                    input_digest=key,
                ))
                if result.launched_ids is not None:
                    launched_this_run.difference_update(set(ids) - set(result.launched_ids))
            else:
                reused_this_run.update(ids)
                if journal_hit:
                    call_id = journal_hit.get("callId")
                    group_id = journal_hit.get("groupId")
            skill_reads.update(result.skill_reads)
            returned = result.knowledge.defectCodeMatches
            artifact_failed = any(match.storageStatus == "artifact_error" for match in returned)
            if (len({m.defectId for m in returned}) != len(returned)
                    or any(m.defectId not in ids for m in returned)):
                raise ValueError("investigation returned duplicate or out-of-group ticket")
            for match in returned:
                prior = restored_by_id.get(match.defectId)
                if prior is not None and result.source == "sdk":
                    # Matching input and workspace identity make these observations reusable.
                    facts = list(match.facts)
                    facts.extend(fact for fact in prior.facts if fact not in facts)
                    match = match.model_copy(update={"facts": facts})
                merged[match.defectId] = match
            if result.source == "sdk":
                knowledge = result.knowledge
            group_partial = artifact_failed or result.knowledge.partial or not result.ok or result.source != "sdk"
            incomplete |= group_partial
            if artifact_failed and stop_reason == "completed":
                stop_reason = "artifact_error"
            group_status = "complete" if _complete(
                knowledge.model_copy(update={
                    "defectCodeMatches": [merged[i] for i in ids],
                    "partial": group_partial,
                }),
                ids,
            ) else "partial"
            accepted = (set(result.accepted_ids) if result.accepted_ids is not None else
                        {match.defectId for match in returned
                         if result.source == "sdk" and match.investigationStatus in {"complete", "partial"}})
            for defect_id in ids:
                state = merged[defect_id].investigationStatus
                ticket_progress[defect_id] = {
                    "state": state if state in {"complete", "partial"} else "failed",
                    "launched": (previous_progress[defect_id]["launched"] or defect_id in launched_this_run
                                 or defect_id in reused_this_run),
                    "accepted": defect_id in accepted or previous_progress[defect_id]["accepted"],
                }
            group_reason = ("artifact_error" if artifact_failed else "completed" if group_status == "complete"
                            else result.stop_reason or "partial")
            if stop_reason == "completed" and group_reason not in {"completed", "partial"}:
                stop_reason = group_reason
            record = {
                "ids": ids, "counts": _counts(ids), "callId": call_id, "groupId": group_id,
                "source": result.source, "detail": result.detail, "cacheKey": key,
                "sdkLaunched": bool(set(ids) & launched_this_run) or bool(
                    reused and journal_hit and journal_hit.get("sdkLaunched")),
                "stage": "map_and_investigation" if n == 0 else "investigation",
                "maxTurns": resolve_cartography_max_turns(req.max_turns, ticket_count=len(ids)),
                "stopReason": group_reason,
                "status": group_status,
                "partial": group_partial or group_status != "complete",
                "turns": journal_hit.get("turns") if reused and journal_hit else result.turns,
                "cost": journal_hit.get("cost") if reused and journal_hit else result.cost,
            }
            records.append(record)
            if not _flush_journal():
                stop_reason = "artifact_error"
                record.update(status="partial", partial=True, stopReason="artifact_error")
            elif dest and group_status == "complete" and result.ok:
                temporary = dest.with_suffix(".tmp")
                try:
                    temporary.write_text(
                        knowledge.model_copy(update={"defectCodeMatches": [merged[i] for i in ids]}).model_dump_json(),
                        encoding="utf-8",
                    )
                    temporary.replace(dest)
                except OSError as err:
                    record["detail"] = "; ".join(x for x in (record["detail"], f"cache write failed: {err}") if x)
        except Exception as err:
            stop_reason = "internal_error"
            for defect_id in ids:
                merged[defect_id] = merged[defect_id].model_copy(update={"investigationStatus": "failed"})
                ticket_progress[defect_id] = {**ticket_progress[defect_id], "state": "failed"}
            records.append({
                "ids": ids, "source": "failed", "detail": str(err), "cacheKey": key,
                "counts": _counts(ids), "callId": call_id, "groupId": group_id,
                "sdkLaunched": bool(set(ids) & launched_this_run),
                "stopReason": "internal_error", "status": "failed",
                "turns": None, "cost": None,
            })
            _flush_journal()
    partial = incomplete or bool(unselected_partial_ids) or any(
        m.investigationStatus in {"not_investigated", "failed", "partial"}
        for m in merged.values()
    )
    if stop_reason == "completed" and partial:
        stop_reason = "partial"
    _flush_journal()
    if journal_error:
        partial = True
        stop_reason = "artifact_error"
    knowledge = knowledge.model_copy(update={
        "defectCodeMatches": list(merged.values()), "partial": partial,
        "investigationRuns": records,
        "investigationProgress": {
            "counts": _counts(tickets), "stopReason": stop_reason,
            "launchedThisRun": len(launched_this_run), "reusedThisRun": len(reused_this_run),
        },
    })
    sources = {r["source"] for r in records}
    source = "sdk" if "sdk" in sources else "sdk_fallback" if sources else "heuristic"
    billing = _aggregate_billing(records)
    detail = "; ".join(str(r["detail"]) for r in records if r.get("detail"))
    if journal_error:
        detail += f"; progress write failed: {journal_error}"
    if stop_reason == "group_budget":
        detail += "; budget_exhausted"
    detail += (
        f"; groups={len(records)}/{len(groups)}; elapsed={time.monotonic()-started:.2f}s; "
        f"partial={partial}; stopReason={stop_reason}; billing={billing.get('aggregate')}"
    )
    return CartographyResult(True, knowledge, source, detail, sorted(skill_reads))
