"""Interpret model observations and publish the Agent2 knowledge handoff."""
from __future__ import annotations

from typing import Any, Optional

from bugfix_contracts import CodeKnowledge, validate_code_knowledge
from bugfix_contracts.code_knowledge import DefectCodeMatch
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.cartography import (
    CartographyMode, CartographyRequest, CartographyResult, CartographyRunner,
    _billing, annotate_investigation_coverage, cartography_mode_from_env,
    investigated_ids_from_parsed, query_cartography, select_prompt_tickets,
)


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
    knowledge = validate_code_knowledge(data)
    all_ids = [m.defectId for m in knowledge.defectCodeMatches]
    knowledge = knowledge.model_copy(
        update={
            "defectCodeMatches": annotate_investigation_coverage(
                knowledge.defectCodeMatches,
                prompt_ids=all_ids,
                investigated_ids=(),
            )
        }
    )
    return CartographyResult(
        ok=True,
        knowledge=knowledge,
        source="heuristic",
    )


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

    from uuid import uuid4

    from bugfix_platform.agents.cartographer.investigation_store import (
        InvestigationRecorder, save_format_repair,
    )

    def create_recorder(max_turns: int | None) -> InvestigationRecorder:
        return InvestigationRecorder(
            req.artifact_dir, req.group_id or "ungrouped", req.call_id or uuid4().hex,
            budget={"max_turns": max_turns},
        )

    def record_repair(call_id: str, before: str, after: str) -> None:
        save_format_repair(
            req.artifact_dir, req.group_id or "ungrouped", call_id, before=before, after=after,
        )

    response = query_cartography(
        req,
        create_recorder=create_recorder if req.artifact_dir else None,
        record_repair=record_repair if req.artifact_dir else None,
    )
    parsed, budget_stop, terminal = response.parsed, response.budget_stop, response.terminal
    turns, cost = response.turns, response.cost
    recorder, observed_paths = response.recorder, response.observed_paths
    billing = _billing(turns, cost, terminal)

    def finish(result: CartographyResult) -> CartographyResult:
        result.skill_reads = response.skill_reads
        if result.turns is None:
            result.turns = turns
        if result.cost is None:
            result.cost = cost
        return result

    if response.error:
        result = heuristic_cartography(req)
        result.source = "sdk_fallback"
        result.detail = "; ".join(part for part in (response.error, billing) if part)
        return finish(result)

    if parsed is not None:
        drop_stats: dict[str, int] = {}
        try:
            if req.investigation_only:
                parsed = {k:v for k,v in parsed.items() if k in {"defectCodeMatches", "partial"}}
            merged = _merge_enrichment(
                req.baseline,
                parsed,
                tickets=req.defect_batch.tickets,
                stats=drop_stats,
            )
            if budget_stop:
                merged["partial"] = True
            from bugfix_platform.agents.cartographer.match_payload import verify_fact_references
            knowledge = validate_code_knowledge(merged)
            prompt_ids = [t.defectId for t, _ in select_prompt_tickets(req)]
            verified = verify_fact_references(
                req.work_dir,
                list(knowledge.defectCodeMatches),
                observed_paths=observed_paths,
                repo_roots=list(req.baseline.repoRoots or []),
            )
            knowledge = knowledge.model_copy(
                update={
                    "defectCodeMatches": annotate_investigation_coverage(
                        verified,
                        prompt_ids=prompt_ids,
                        investigated_ids=investigated_ids_from_parsed(parsed),
                    )
                }
            )
        except Exception as err:  # noqa: BLE001
            from bugfix_platform.agents.cartographer.match_payload import normalize_group_matches, verify_fact_references
            allowed = {t.defectId for t in req.defect_batch.tickets}
            group = normalize_group_matches(parsed or {}, requested_ids=allowed, raw_ref="sdk")
            data = req.baseline.model_dump()
            by_id = {m["defectId"]: m for m in data.get("defectCodeMatches") or []}
            for match in group.accepted:
                by_id[match.defectId] = match.model_dump()
            data["defectCodeMatches"] = list(by_id.values())
            data["partial"] = True
            hints = list(data.get("secondaryHints") or [])
            hints.append(f"internal_error:{err}")
            data["secondaryHints"] = hints
            try:
                knowledge = validate_code_knowledge(data)
                knowledge = knowledge.model_copy(
                    update={
                        "defectCodeMatches": verify_fact_references(
                            req.work_dir,
                            list(knowledge.defectCodeMatches),
                            observed_paths=observed_paths,
                            repo_roots=list(req.baseline.repoRoots or []),
                        )
                    }
                )
                detail = _with_drop_detail(billing, drop_stats)
                if recorder is not None and recorder.artifact_error is None:
                    recorder.finalize(status="saved", stop_reason="internal_error", turns=turns, cost=cost, terminal=terminal)
                return finish(CartographyResult(
                    ok=True, knowledge=knowledge, source="sdk",
                    detail="; ".join(x for x in [detail, f"internal_error:{err}"] if x),
                ))
            except Exception:
                if budget_stop:
                    return finish(_sdk_keep_baseline(req, billing))
                fallback = heuristic_cartography(req)
                fallback.source = "sdk_fallback"
                fallback.detail = f"enriched code-knowledge invalid: {err}" + (f"; {billing}" if billing else "")
                return finish(fallback)
        detail = _with_drop_detail(billing, drop_stats)
        if recorder is not None and recorder.artifact_error is None:
            recorder.finalize(
                status="saved",
                stop_reason=terminal or "completed",
                turns=turns,
                cost=cost,
                terminal=terminal,
            )
        return finish(CartographyResult(
            ok=True, knowledge=knowledge, source="sdk", detail=detail or None
        ))

    if budget_stop:
        return finish(_sdk_keep_baseline(req, billing))

    fallback = heuristic_cartography(req)
    fallback.source = "sdk_fallback"
    fallback.detail = "sdk returned no parseable JSON cartography"
    return finish(fallback)


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
    from bugfix_platform.agents.cartographer.match_payload import normalize_group_matches

    allowed = {t.defectId for t in tickets} if tickets is not None else {m.defectId for m in baseline.defectCodeMatches}
    group = normalize_group_matches(parsed, requested_ids=allowed, raw_ref="sdk")
    for issue in group.issues:
        _bump(stats, issue.reason)
    parsed = dict(parsed)
    parsed.update({k: v for k, v in group.shared.items() if v is not None})
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
    if group.accepted:
        by_id = {m["defectId"]: m for m in data.get("defectCodeMatches") or []}
        for match in group.accepted:
            did = match.defectId
            sdk_ids.add(did)
            cleaned = match.model_dump()
            orig = by_id.get(did) or {}
            for key in ("title", "clusterId"):
                if not cleaned.get(key) and orig.get(key):
                    cleaned[key] = orig[key]
            by_id[did] = cleaned
        data["defectCodeMatches"] = list(by_id.values())
    if isinstance(group.shared.get("secondaryHints"), list):
        parsed = {**parsed, "secondaryHints": group.shared["secondaryHints"]}
    if isinstance(group.shared.get("techStack"), dict):
        parsed = {**parsed, "techStack": group.shared["techStack"]}
    if isinstance(group.shared.get("architecture"), dict):
        parsed = {**parsed, "architecture": group.shared["architecture"]}
    if isinstance(group.shared.get("conventions"), dict):
        parsed = {**parsed, "conventions": group.shared["conventions"]}
    if isinstance(group.shared.get("boundSkills"), list):
        parsed = {**parsed, "boundSkills": group.shared["boundSkills"]}
    if isinstance(group.shared.get("partial"), bool):
        parsed = {**parsed, "partial": group.shared["partial"]}
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
                merged_matches.append((match if match.facts or match.searchedScopes else (orig or match)).model_dump())
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
    """把模型条目收成契约允许的形状；实在不可用才返回 ``None``。"""
    from bugfix_platform.agents.cartographer.match_payload import normalize_sdk_match

    defect_id = str(item.get("defectId") or "")
    result = normalize_sdk_match(
        item,
        requested_ids={defect_id} if defect_id else set(),
        raw_ref=defect_id or "item",
    )
    for issue in result.issues:
        _bump(stats, issue.reason)
    if result.accepted is None:
        return None
    return result.accepted.model_dump()



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
        from bugfix_contracts.code_knowledge import ArchModule
        try:
            clean = ArchModule.model_validate(item).model_dump()
        except Exception:  # noqa: BLE001
            continue
        mid = str(clean.get("id"))
        if mid in index:
            merged = dict(out[index[mid]])
            merged.update({k: v for k, v in clean.items() if v is not None and v != ""})
            out[index[mid]] = merged
        else:
            index[mid] = len(out)
            out.append(clean)
    return out
