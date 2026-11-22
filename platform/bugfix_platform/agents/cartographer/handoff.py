"""Interpret model observations and publish the Agent2 knowledge handoff."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Optional

from bugfix_contracts import CodeKnowledge, validate_code_knowledge
from bugfix_contracts.code_knowledge import DefectCodeMatch, ParseIssue
from bugfix_platform.agents.cartographer.match_payload import (
    GroupParseResult, normalize_group_matches, verify_fact_references,
)
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.cartography import (
    CartographyMode, CartographyRequest, CartographyResult, CartographyRunner,
    _billing, annotate_investigation_coverage, cartography_mode_from_env,
    query_cartography, select_prompt_tickets,
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
        fallback.launched_ids = []
        fallback.accepted_ids = []
        fallback.stop_reason = "sdk_error"
        return fallback

    from uuid import uuid4

    from bugfix_platform.agents.cartographer.investigation_store import (
        InvestigationRecorder, save_format_repair,
    )

    def create_recorder(max_turns: int | None) -> InvestigationRecorder:
        try:
            sdk_version = version("claude-agent-sdk")
        except PackageNotFoundError:
            sdk_version = ""
        return InvestigationRecorder(
            req.artifact_dir, req.group_id or "ungrouped", req.call_id or uuid4().hex,
            input_digest=req.input_digest or sha256(req.defect_batch.model_dump_json().encode()).hexdigest(),
            budget={"max_turns": max_turns},
            sdk_version=sdk_version,
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
    budget_stop, terminal = response.budget_stop, response.terminal
    turns, cost = response.turns, response.cost
    recorder, observed_paths = response.recorder, response.observed_paths
    billing = _billing(turns, cost, terminal)
    prompt_ids = [ticket.defectId for ticket, _ in select_prompt_tickets(req)]
    group = GroupParseResult()
    accepted_ids: list[str] = []

    def finish(result: CartographyResult, *, status: str = "saved", reason: str | None = None) -> CartographyResult:
        artifact_error = response.artifact_error
        if recorder is not None:
            try:
                recorder.finalize(
                    status="artifact_error" if artifact_error else status,
                    stop_reason="artifact_error" if artifact_error else reason or terminal or "completed",
                    turns=turns, cost=cost, terminal=terminal,
                    diagnostics={
                        "repair": {"requestedIds": response.repair_ids, "status": response.repair_status},
                        "issues": [
                            issue.model_copy(update={"fieldPath": issue.fieldPath.split("#", 1)[-1]}).model_dump()
                            for issue in group.issues
                        ],
                        "fieldRefs": group.field_refs,
                        "elementRefs": {"candidates": group.candidate_refs, "facts": group.fact_refs},
                        "issueCounts": dict(Counter(issue.reason for issue in group.issues)),
                        "acceptedMatches": [match.model_dump() for match in group.accepted],
                        "acceptedIds": accepted_ids,
                        "launchedIds": response.launched_ids,
                    },
                )
            except OSError as err:
                artifact_error = artifact_error or str(err)
        if artifact_error:
            matches = [match.model_copy(update={
                "storageStatus": "artifact_error",
                "investigationStatus": (
                    "partial" if match.investigationStatus == "complete" else match.investigationStatus
                ),
            }) for match in result.knowledge.defectCodeMatches]
            result.knowledge = result.knowledge.model_copy(update={"partial": True, "defectCodeMatches": matches})
            result.detail = "; ".join(part for part in (result.detail, f"artifact_error: {artifact_error}") if part)
        result.launched_ids = response.launched_ids
        result.accepted_ids = accepted_ids
        result.stop_reason = "artifact_error" if artifact_error else reason or status
        result.skill_reads = response.skill_reads
        if result.turns is None:
            result.turns = turns
        if result.cost is None:
            result.cost = cost
        return result

    if response.error:
        group.issues.append(ParseIssue(fieldPath="response", reason="sdk_error", action="record",
                                       rawRef=response.parsed_ref))
        result = heuristic_cartography(req)
        result.source = "sdk_fallback"
        result.detail = "; ".join(part for part in (response.error, billing) if part)
        return finish(result, status="sdk_error", reason="sdk_error")

    group = normalize_group_matches(response.parsed or {}, requested_ids=set(prompt_ids),
                                    raw_ref=response.parsed_ref)
    if response.parsed is None:
        group.issues.append(ParseIssue(fieldPath="response", reason="no_business_envelope", action="reject",
                                       rawRef=response.parsed_ref))
    if response.repair_parsed is not None:
        repair = normalize_group_matches(response.repair_parsed, requested_ids=set(response.repair_ids),
                                         raw_ref=response.repair_ref)
        group.accepted.extend(repair.accepted)
        group.issues.extend(repair.issues)
        group.field_refs.update(repair.field_refs)
        group.candidate_refs.update(repair.candidate_refs)
        group.fact_refs.update(repair.fact_refs)
        if response.parsed is None:
            group.shared = repair.shared
    if req.investigation_only:
        group.shared = {key: value for key, value in group.shared.items() if key == "partial"}

    accepted_ids = [match.defectId for match in group.accepted
                    if match.candidates or _has_investigation(match)]
    investigated_ids = [match.defectId for match in group.accepted]
    missing = set(prompt_ids) - set(investigated_ids)
    if response.parsed is not None or response.repair_parsed is not None:
        drop_stats: dict[str, int] = {}
        try:
            merged = _merge_enrichment(req.baseline, {}, tickets=req.defect_batch.tickets,
                                       stats=drop_stats, group=group)
            if missing or (budget_stop and response.repair_status != "returned"):
                merged["partial"] = True
            knowledge = validate_code_knowledge(merged)
        except Exception as err:  # noqa: BLE001
            group.issues.append(ParseIssue(fieldPath="codeKnowledge", reason="internal_error", action="record",
                                           rawRef=response.parsed_ref))
            by_id = {match.defectId: match for match in req.baseline.defectCodeMatches}
            by_id.update((match.defectId, match) for match in group.accepted)
            knowledge = req.baseline.model_copy(update={
                "defectCodeMatches": list(by_id.values()), "partial": True,
            })
            return finish(CartographyResult(
                ok=True, knowledge=knowledge, source="sdk", detail=f"internal_error:{err}",
            ), status="internal_error", reason="internal_error")

        matches = {match.defectId: match for match in knowledge.defectCodeMatches}
        for defect_id in prompt_ids:
            matches.setdefault(defect_id, DefectCodeMatch(defectId=defect_id))
        def diagnose_reference(defect_id: str, index: int) -> None:
            refs = group.fact_refs.get(defect_id, [])
            if index < len(refs):
                ref = refs[index] + ".reference"
                group.issues.append(ParseIssue(fieldPath=ref, reason="reference_not_verified",
                                               action="record", rawRef=ref))

        verified = verify_fact_references(
            req.work_dir, list(matches.values()), observed_paths=observed_paths,
            repo_roots=list(req.baseline.repoRoots or []),
            on_unverified=diagnose_reference,
        )
        covered = annotate_investigation_coverage(
            verified, prompt_ids=prompt_ids, investigated_ids=investigated_ids,
        )
        accepted_ids = [match.defectId for match in covered if match.defectId in accepted_ids
                        and match.acceptanceStatus == "accepted" and (match.candidates or _has_investigation(match))]
        partial = (bool(group.shared.get("partial")) or (budget_stop and response.repair_status != "returned")
                   or any(match.investigationStatus != "complete" for match in covered if match.defectId in prompt_ids))
        knowledge = knowledge.model_copy(update={"defectCodeMatches": covered, "partial": partial})
        detail = _with_drop_detail(billing, drop_stats)
        return finish(CartographyResult(ok=True, knowledge=knowledge, source="sdk", detail=detail),
                      reason="output_invalid" if missing else "partial" if knowledge.partial else "completed")

    if budget_stop:
        return finish(_sdk_keep_baseline(req, billing), status="output_invalid", reason="output_invalid")

    fallback = heuristic_cartography(req)
    fallback.source = "sdk_fallback"
    fallback.detail = "sdk returned no parseable JSON cartography"
    return finish(fallback, status="output_invalid", reason="output_invalid")


def _has_investigation(match: DefectCodeMatch) -> bool:
    return any((match.facts, match.searchedScopes, match.hypotheses,
                match.ruledOut, match.openQuestions, match.nextChecks))


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
    group: GroupParseResult | None = None,
) -> dict[str, Any]:
    if group is None:
        allowed = {t.defectId for t in tickets} if tickets is not None else {m.defectId for m in baseline.defectCodeMatches}
        group = normalize_group_matches(parsed, requested_ids=allowed, raw_ref="sdk")
    for issue in group.issues:
        if issue.action != "record":
            _bump(stats, issue.reason)
    parsed = group.shared
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
                if orig.get(key):
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
    def diagnose_candidate(defect_id: str, index: int, reason: str) -> None:
        refs = group.candidate_refs.get(defect_id, [])
        if index < len(refs):
            ref = refs[index]
            group.issues.append(ParseIssue(fieldPath=ref, reason=reason, action="drop", rawRef=ref))

    merged_matches: list[dict[str, Any]] = []
    for match in filter_existing_candidates(
        baseline.workDir,
        parsed_matches,
        profile=baseline.cartographyProfile,
        architecture=baseline.architecture,
        variant_by_id=variant_by_id or None,
        stats=stats,
        on_drop=diagnose_candidate,
    ):
        if match.defectId in sdk_ids:
            if not match.candidates:
                orig = baseline_by_id.get(match.defectId)
                merged_matches.append((match if _has_investigation(match) else (orig or match)).model_dump())
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
