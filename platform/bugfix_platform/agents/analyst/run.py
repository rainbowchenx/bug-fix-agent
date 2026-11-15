from __future__ import annotations

import hashlib
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4

from bugfix_platform.agents.analyst.attempt_store import AttemptStoreBusy, save_attempt, store_lock
from bugfix_platform.agents.analyst.checks import run_check
from bugfix_platform.agents.analyst.context import build_task_context
from bugfix_platform.agents.analyst.evidence import validate_edit_decision
from bugfix_platform.agents.analyst.loop import run_ticket
from bugfix_platform.agents.analyst.report import render_report
from bugfix_platform.agents.analyst.route import route_ticket, slice_ticket
from bugfix_platform.agents.analyst.workspace import capture_workspace, collect_patch, prepare_workspace
from bugfix_contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_analysis_report,
)
from bugfix_contracts.analysis_report import TicketReport
from bugfix_contracts.defect_batch import BatchTicket
from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    EditDecision,
    Evidence,
    InputRevision,
    PatchFile,
    PatchSet,
    TaskContext,
    VerificationRun,
)
from bugfix_platform.sdk.analyze import (
    AnalyzeRequest,
    AnalyzeRunner,
    analyze_mode_from_env,
    create_analyze_runner,
)
from bugfix_platform.sdk.codegraph import ensure_codegraph
from bugfix_platform.sdk.cartography import profile_reading_playbook
from bugfix_platform.sdk.fix import (
    FixRequest,
    FixRunner,
    apply_fix_from_env,
    create_fix_runner,
)
from bugfix_platform.sdk.skill_inject import discover_analyze_skills, discover_fix_skills


def run_analyst(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    code_knowledge: CodeKnowledge,
    open_mr: bool = False,
    apply_fix: Optional[bool] = None,
    analyze_mode: Optional[str] = None,
    extra_skill_dirs: Optional[Sequence[str | Path]] = None,
    analyze_fn: Optional[AnalyzeRunner] = None,
    fix_fn: Optional[FixRunner] = None,
    analyze_limit: Optional[int] = None,
    artifact_dir: Optional[str | Path] = None,
    ticket_ids: Optional[Sequence[str]] = None,
    revisions: Optional[Mapping[str, InputRevision]] = None,
    session_ids: Optional[Mapping[str, str]] = None,
) -> AnalysisReport:
    """Agent-3 公开入口：产出 ``analysis-report``（默认只出报告、不改码）。

    对匹配池中的每张票::

        route_ticket（确定性 hint）──► analyze 会话（needs_info 除外）
                                  └──► ``apply_fix`` 时经 EditDecision 门槛进入 run_ticket

    - ``needs_ticket_info`` 停在路由器（不调 LLM）。
    - 空候选仍进 analyze（软起点；D4）。
    - ``apply_fix`` 默认关：可修票也是 ``plan_only``。
    - 单票校验失败 → ``other_blocked``，整份报告仍继续。
    - ``open_mr`` 只记录请求标志；没有真实 ``mrUrl`` 时 ``integrateMode`` 仍为 ``none``。
    - ``revisions`` 按缺陷 ID 注入补充输入，resume 二次执行走同一入口。

    Args:
        work_dir: 目标代码根。
        defect_batch: 已校验的缺陷批次。
        code_knowledge: Agent-2 产物。
        open_mr: 只改报告 ``integrateMode`` 标志。
        apply_fix: 是否跑第二段改码；``None`` 时看 ``BUGFIX_APPLY_FIX``。
        analyze_mode: ``heuristic`` / ``sdk``；``None`` 时看环境变量。
        extra_skill_dirs: 与 Agent-2 相同的仓特异性 skill 根目录。
        analyze_fn: 可注入的 ``AnalyzeRunner``（测试用）。
        fix_fn: 可注入的 ``FixRunner``（测试用）。
        analyze_limit: 最多 analyze 几张票。
        artifact_dir: patch 文件目录（缺省 ``workDir/.bugfix/patches``）。
        ticket_ids: 若给出则只处理这些缺陷。
        revisions: 票 ID → 补充 InputRevision。
        session_ids: 票 ID → 续接会话。

    Returns:
        通过 ``validate_analysis_report`` 的 ``AnalysisReport``。
    """
    work_dir = str(work_dir)
    want_fix = apply_fix_from_env(apply_fix)
    match_by_id = {m.defectId: m for m in code_knowledge.defectCodeMatches}
    injected = discover_analyze_skills(
        work_dir,
        repo_roots=code_knowledge.repoRoots,
        extra_dirs=extra_skill_dirs,
    )
    bound_skills = list(dict.fromkeys(s.name for s in injected))[:40]
    runner = analyze_fn or create_analyze_runner(analyze_mode_from_env(analyze_mode))
    fixer: Optional[FixRunner] = None
    fix_skills: tuple = ()
    if want_fix:
        fix_skills = tuple(
            discover_fix_skills(
                work_dir,
                repo_roots=code_knowledge.repoRoots,
                extra_dirs=extra_skill_dirs,
            )
        )
        fixer = fix_fn or create_fix_runner()
    remaining = analyze_limit if analyze_limit is not None else _limit_from_env()
    out_dir = str(artifact_dir) if artifact_dir is not None else None
    cg_status = ensure_codegraph(work_dir, code_knowledge.repoRoots)
    if cg_status.detail:
        print(f"[agent3] codegraph={cg_status.detail[:240]}", file=sys.stderr)
    spec_atlas = code_knowledge.specAtlas.model_dump()
    wanted = {str(x) for x in ticket_ids} if ticket_ids is not None else None
    rev_map = dict(revisions or {})
    sess_map = dict(session_ids or {})
    locked = bool(out_dir)
    lock_cm = store_lock(Path(out_dir)) if out_dir else nullcontext()

    with lock_cm:
        tickets: list[dict[str, Any]] = []
        analyze_sources: list[str] = []
        for t in defect_batch.tickets:
            if wanted is not None and t.defectId not in wanted:
                continue
            revision = rev_map.get(t.defectId)
            ticket = _ticket_with_revision(t, revision)
            if not is_match_pool(ticket.pool):
                entry = _sideline_entry(ticket)
                tickets.append(
                    _persist_ticket_entry(
                        out_dir,
                        entry,
                        _attempt_from_entry(entry, revision=revision, session_id=sess_map.get(ticket.defectId)),
                        already_locked=locked,
                    )
                )
                continue
            routed = route_ticket(ticket, match_by_id.get(ticket.defectId))
            entry: dict[str, Any] = {
                "defectId": ticket.defectId,
                "ticket": slice_ticket(ticket),
                **routed,
            }

            if routed["outcome"] != "needs_ticket_info" and (
                remaining is None or remaining > 0
            ):
                result = runner(
                    AnalyzeRequest(
                        work_dir=work_dir,
                        ticket=ticket,
                        routed=routed,
                        injected_skills=tuple(injected),
                        cartography_profile=code_knowledge.cartographyProfile,
                        architecture=code_knowledge.architecture.model_dump(),
                        reading_playbook=profile_reading_playbook(
                            code_knowledge.cartographyProfile
                        ),
                        apply_fix=want_fix,
                        spec_atlas=spec_atlas,
                        codegraph=cg_status,
                    )
                )
                entry.update(result.payload)
                analyze_sources.append(result.source)
                _note = " ".join(str(result.detail or "").split())
                if _note:
                    print(
                        f"[agent3] analyze={result.source}; {_note[:200]}", file=sys.stderr
                    )
                loc = dict(entry.get("localization") or {})
                note_bits = [x for x in [loc.get("notes"), f"analyze={result.source}"] if x]
                if result.detail:
                    note_bits.append(result.detail)
                loc["notes"] = "; ".join(note_bits)
                entry["localization"] = loc
                if remaining is not None:
                    remaining -= 1

            if not want_fix and entry.get("outcome") == "patch_ready":
                entry["outcome"] = "plan_only"
                entry["patch"] = None
                if not (entry.get("proposedFix") or {}).get("summary"):
                    entry["proposedFix"] = {
                        "summary": "See rootCause; patch gated off by applyFix=false",
                        "steps": [],
                        "targetFiles": [],
                    }
                entry["blockers"] = None

            snapshot = capture_workspace(Path(work_dir))
            ctx = _context_with_analysis(
                build_task_context(
                    ticket,
                    code_knowledge,
                    revision=revision,
                    snapshot=snapshot,
                    generate_patch=want_fix,
                ),
                entry,
            )
            decision = _decision_from_entry(entry, ctx)
            gate_errors = validate_edit_decision(ctx, decision)
            if gate_errors:
                decision = EditDecision.model_validate(
                    {
                        **decision.model_dump(),
                        "allowed": False,
                        "reason": "; ".join(gate_errors),
                    }
                )
            session_id = sess_map.get(ticket.defectId) or uuid4().hex[:12]
            attempt: AttemptRecord
            if want_fix and fixer is not None and decision.allowed and entry.get("outcome") in (
                "plan_only",
                "patch_ready",
            ):
                attempt, entry = _run_fix_loop(
                    work_dir=work_dir,
                    ticket=ticket,
                    entry=entry,
                    context=ctx.model_copy(update={"generatePatch": True}),
                    decision=decision,
                    fixer=fixer,
                    fix_fn=fix_fn,
                    fix_skills=fix_skills,
                    out_dir=out_dir,
                    snapshot=snapshot,
                    revision=revision,
                    session_id=session_id,
                )
            else:
                if want_fix and entry.get("outcome") == "patch_ready" and not decision.allowed:
                    entry["outcome"] = "plan_only"
                    entry["patch"] = None
                    if not (entry.get("proposedFix") or {}).get("summary"):
                        entry["proposedFix"] = {
                            "summary": "See rootCause; edit gate rejected this turn",
                            "steps": [],
                            "targetFiles": [],
                        }
                    entry["blockers"] = None
                    loc = dict(entry.get("localization") or {})
                    loc["notes"] = "; ".join(
                        x for x in [loc.get("notes"), f"edit-gate: {decision.reason}"] if x
                    )
                    entry["localization"] = loc
                attempt = _attempt_from_entry(
                    entry,
                    revision=revision,
                    session_id=session_id,
                    decision=decision,
                    evidence=list(ctx.evidence),
                )

            tickets.append(
                _persist_ticket_entry(out_dir, entry, attempt, already_locked=locked)
            )

        if analyze_sources:
            tally: dict[str, int] = {}
            for src in analyze_sources:
                tally[src] = tally.get(src, 0) + 1
            parts = ", ".join(f"{k}×{v}" for k, v in sorted(tally.items()))
            print(f"[agent3] analyze summary: {parts}", file=sys.stderr)

        by_outcome: dict[str, int] = {}
        for tr in tickets:
            by_outcome[tr["outcome"]] = by_outcome.get(tr["outcome"], 0) + 1

        report = {
            "schemaVersion": ANALYSIS_REPORT_SCHEMA_VERSION,
            "productLine": defect_batch.productLine,
            "workDir": work_dir,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "openMr": open_mr,
            "applyFix": want_fix,
            "mrUrl": None,
            "integrateMode": "none",
            "summary": {"total": len(tickets), "byOutcome": by_outcome},
            "boundSkills": bound_skills,
            "tickets": tickets,
        }
        if out_dir:
            _write_markdown_report(out_dir, defect_batch.productLine, tickets)
        return validate_analysis_report(report)


_SIDELINE_OUTCOME = {
    "duplicate": ("other_blocked", "duplicate"),
    "excluded": ("other_blocked", "excluded"),
    "security": ("not_code", "security"),
    "hard_reject": ("not_code", "hard_reject"),
}

_OUTCOME_RESOLUTION = {
    "plan_only": "analysis_only",
    "patch_ready": "patch_produced",
    "needs_ticket_info": "needs_information",
    "needs_test_env": "needs_environment",
    "needs_design_input": "needs_business_decision",
    "not_code": "external_component",
    "config_or_dependency": "external_component",
    "unlocalized": "unlocalized",
    "other_blocked": "incomplete",
}

def _ticket_with_revision(ticket: BatchTicket, revision: Optional[InputRevision]) -> BatchTicket:
    if revision is None:
        return ticket
    updates: dict[str, Any] = {}
    if revision.observed:
        updates["observed"] = revision.observed
    if revision.expected:
        updates["expected"] = revision.expected
    if revision.steps:
        updates["steps"] = revision.steps
    if revision.attachments:
        updates["attachmentRefs"] = list(revision.attachments)
    return ticket.model_copy(update=updates) if updates else ticket


def _context_with_analysis(context: TaskContext, entry: dict[str, Any]) -> TaskContext:
    extra = list(context.evidence)
    seen = {e.evidenceId for e in extra}
    loc = entry.get("localization") or {}
    for i, cand in enumerate(loc.get("candidates") or [], start=1):
        if not isinstance(cand, dict) or not cand.get("path"):
            continue
        eid = f"a3-loc-{entry.get('defectId')}-{i}"
        if eid in seen:
            continue
        extra.append(
            Evidence(
                evidenceId=eid,
                category="code_observation",
                source=str(cand.get("source") or "analyze"),
                summary=str(cand.get("why") or cand["path"]),
                path=str(cand["path"]),
                repoId=str(cand.get("repoPath") or "."),
                validity="pending_review",
            )
        )
        seen.add(eid)
    return context.model_copy(update={"evidence": extra})


def _decision_from_entry(entry: dict[str, Any], context: TaskContext) -> EditDecision:
    root = entry.get("rootCause") or {}
    proposed = entry.get("proposedFix") or {}
    loc = entry.get("localization") or {}
    ticket = entry.get("ticket") or {}
    summary = str(root.get("summary") or "").strip()
    rationale = str(proposed.get("summary") or "").strip()
    paths: list[str] = []
    for cand in loc.get("candidates") or []:
        if isinstance(cand, dict) and cand.get("path"):
            paths.append(str(cand["path"]))
    for item in proposed.get("targetFiles") or []:
        paths.append(str(item))
    association = "; ".join(dict.fromkeys(paths)) or "unspecified"
    behavior = (
        str(ticket.get("expected") or "").strip()
        or str(ticket.get("observed") or "").strip()
        or summary
        or "defect behavior"
    )
    return EditDecision(
        allowed=True,
        behaviorTarget=behavior,
        codeAssociation=association,
        mechanism=summary or "unspecified",
        editRationale=rationale,
        evidenceRefs=[e.evidenceId for e in context.evidence],
        openQuestions=list(root.get("openQuestions") or []),
    )


def _run_fix_loop(
    *,
    work_dir: str,
    ticket: BatchTicket,
    entry: dict[str, Any],
    context: TaskContext,
    decision: EditDecision,
    fixer: FixRunner,
    fix_fn: Optional[FixRunner],
    fix_skills: tuple,
    out_dir: Optional[str],
    snapshot: Any,
    revision: Optional[InputRevision],
    session_id: str,
) -> tuple[AttemptRecord, dict[str, Any]]:
    last_payload: dict[str, Any] = {}

    def edit(_ctx: TaskContext, _decision: EditDecision) -> dict[str, Any]:
        if fix_fn is not None:
            wt = Path(work_dir)
        else:
            dest = Path(out_dir or work_dir) / ".bugfix" / "worktrees" / ticket.defectId
            wt = prepare_workspace(snapshot, dest)
        result = fixer(
            FixRequest(
                work_dir=work_dir,
                ticket=ticket,
                analysis=dict(entry),
                worktree_path=str(wt),
                artifact_dir=out_dir,
                injected_skills=fix_skills,
            )
        )
        last_payload.clear()
        last_payload.update(result.payload or {})
        last_payload["_source"] = result.source
        last_payload["_detail"] = result.detail
        archive_root = Path(out_dir) if out_dir else wt / ".bugfix"
        collected = collect_patch(snapshot, wt, archive_dir=archive_root)
        diffs: list[str] = []
        for item in collected.patches:
            path = Path(item.archivePath)
            if path.is_file():
                diffs.append(path.read_text(encoding="utf-8", errors="replace"))
        report_patch = last_payload.get("patch") or {}
        patch_path = report_patch.get("path") if isinstance(report_patch, dict) else None
        if patch_path:
            file_path = Path(str(patch_path))
            if file_path.is_file():
                text = file_path.read_text(encoding="utf-8", errors="replace")
                diffs.append(text)
                if not collected.patches:
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                    collected = PatchSet(
                        patchSetId=uuid4().hex[:12],
                        delivery="candidate",
                        baselineHead=getattr(snapshot, "head", None),
                        summary=str(report_patch.get("summary") or file_path.name),
                        patches=[
                            PatchFile(
                                path=file_path.name,
                                kind="modify",
                                digest=digest,
                                archivePath=str(file_path),
                            )
                        ],
                    )
        return {"diff": "\n".join(diffs), "patchSet": collected}

    def check(_ctx: TaskContext, _decision: EditDecision, _patch: Any) -> VerificationRun:
        specs = list((entry.get("suggestedVerify") or {}).get("commands") or [])
        if specs and isinstance(specs[0], dict) and specs[0].get("command"):
            return run_check(specs[0], Path(work_dir))
        return VerificationRun(
            command=["suggested-verify"],
            result="not_run",
            coverage="suggested_only",
        )

    attempt = run_ticket(
        context,
        {
            "analyze": lambda _ctx: decision,
            "edit": edit,
            "check": check,
        },
    )
    attempt = attempt.model_copy(
        update={
            "revisionId": revision.revisionId if revision else attempt.revisionId,
            "sessionId": session_id,
            "evidence": list(context.evidence),
            "editDecision": attempt.editDecision or decision,
        }
    )
    loc = dict(entry.get("localization") or {})
    loc["notes"] = "; ".join(
        x
        for x in [
            loc.get("notes"),
            f"fix={last_payload.get('_source')}",
            last_payload.get("_detail"),
            None if attempt.editDecision is None else attempt.editDecision.reason,
        ]
        if x
    )
    entry["localization"] = loc
    if attempt.resolution == "patch_produced" and attempt.patchSet and attempt.patchSet.patches:
        entry["outcome"] = "patch_ready"
        payload_patch = last_payload.get("patch")
        if isinstance(payload_patch, dict) and payload_patch.get("path"):
            entry["patch"] = payload_patch
        else:
            first = attempt.patchSet.patches[0]
            entry["patch"] = {
                "path": first.archivePath,
                "summary": attempt.patchSet.summary or first.path,
            }
        entry["blockers"] = None
        if not (entry.get("proposedFix") or {}).get("summary"):
            entry["proposedFix"] = {
                "summary": entry["patch"].get("summary") or "candidate patch",
                "steps": [],
                "targetFiles": [p.path for p in attempt.patchSet.patches],
            }
    else:
        if entry.get("outcome") == "patch_ready":
            entry["outcome"] = "plan_only"
            entry["patch"] = None
            entry["blockers"] = None
            if not (entry.get("proposedFix") or {}).get("summary"):
                entry["proposedFix"] = {
                    "summary": "See rootCause; no candidate patch this turn",
                    "steps": [],
                    "targetFiles": [],
                }
    return attempt, entry


def _sideline_entry(ticket: Any) -> dict[str, Any]:
    """匹配池外的票仍进报告，不假装已调查。"""
    outcome, kind = _SIDELINE_OUTCOME.get(ticket.pool, ("other_blocked", ticket.pool))
    detail = ticket.reasonDetail or f"pool={ticket.pool}"
    return {
        "defectId": ticket.defectId,
        "ticket": slice_ticket(ticket),
        "outcome": outcome,
        "proposedFix": None,
        "patch": None,
        "blockers": {"kind": kind, "detail": detail},
        "rootCause": {
            "summary": f"Ticket not in match pool ({ticket.pool})",
            "ruledOut": [],
            "openQuestions": [],
        },
        "localization": {"candidates": [], "notes": f"pool={ticket.pool}"},
        "suggestedVerify": {"steps": [], "executed": False},
        "confidence": "low",
        "verifyStatus": "skipped",
    }


def _attempt_from_entry(
    entry: dict[str, Any],
    *,
    revision: Optional[InputRevision] = None,
    session_id: Optional[str] = None,
    decision: Optional[EditDecision] = None,
    evidence: Optional[list[Evidence]] = None,
    patch_set: Optional[PatchSet] = None,
    checks: Optional[list[VerificationRun]] = None,
) -> AttemptRecord:
    outcome = str(entry.get("outcome") or "other_blocked")
    kind = str((entry.get("blockers") or {}).get("kind") or "")
    resolution = "excluded" if kind in {"excluded", "duplicate"} else _OUTCOME_RESOLUTION.get(
        outcome, "incomplete"
    )
    return AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId=uuid4().hex[:12],
        defectId=str(entry.get("defectId") or "unknown"),
        revisionId=revision.revisionId if revision else None,
        sessionId=session_id,
        execution="completed",
        resolution=resolution,  # type: ignore[arg-type]
        patchDelivery="candidate" if outcome == "patch_ready" else "none",
        editDecision=decision,
        patchSet=patch_set,
        checks=list(checks or []),
        evidence=list(evidence or []),
    )


def _persist_ticket_entry(
    out_dir: Optional[str],
    entry: dict[str, Any],
    attempt: AttemptRecord,
    *,
    already_locked: bool = False,
) -> dict[str, Any]:
    coerced = _coerce_ticket_entry(entry)
    if not out_dir:
        return coerced
    try:
        save_attempt(Path(out_dir), attempt, already_locked=already_locked)
        return coerced
    except (AttemptStoreBusy, OSError) as err:
        failed = dict(entry)
        failed["outcome"] = "other_blocked"
        failed["proposedFix"] = None
        failed["patch"] = None
        failed["blockers"] = {
            "kind": "other_blocked",
            "detail": f"persist failed: {err}",
        }
        return _coerce_ticket_entry(failed)


def _write_markdown_report(out_dir: str, product_line: str, tickets: list[dict[str, Any]]) -> None:
    path = Path(out_dir) / "analysis-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_report({"batchId": product_line, "tickets": tickets}),
        encoding="utf-8",
    )


def _coerce_ticket_entry(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        return TicketReport.model_validate(entry).model_dump()
    except Exception as err:  # noqa: BLE001
        return {
            "defectId": entry.get("defectId") or "unknown",
            "ticket": entry.get("ticket") or {},
            "localization": entry.get("localization")
            or {"candidates": [], "notes": "ticket validation failed"},
            "rootCause": {
                "summary": "Agent-3 ticket payload failed schema validation",
                "ruledOut": [],
                "openQuestions": [str(err)],
            },
            "outcome": "other_blocked",
            "proposedFix": None,
            "patch": None,
            "blockers": {
                "kind": "other_blocked",
                "detail": f"invalid ticket report: {err}",
            },
            "suggestedVerify": {"steps": [], "executed": False},
            "confidence": "low",
            "verifyStatus": "skipped",
        }


def _limit_from_env() -> Optional[int]:
    import os

    raw = os.environ.get("BUGFIX_ANALYZE_LIMIT")
    if raw is None or raw.strip() == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None
