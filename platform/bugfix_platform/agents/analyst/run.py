from __future__ import annotations

import hashlib
import json
import re
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
from bugfix_platform.agents.analyst.feedback import classify_patch_state
from bugfix_platform.agents.analyst.loop import run_ticket
from bugfix_platform.agents.analyst.report import render_report
from bugfix_platform.agents.analyst.route import route_ticket, slice_ticket
from bugfix_platform.agents.analyst.sessions import load_latest_attempt
from bugfix_platform.agents.analyst.workspace import (
    capture_workspace,
    collect_patch,
    prepare_workspace,
    workspace_digest,
)
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

        def _one(raw: BatchTicket) -> dict[str, Any]:
            nonlocal remaining
            revision = rev_map.get(raw.defectId)
            ticket = _promote_after_revision(_ticket_with_revision(raw, revision), revision)
            if not is_match_pool(ticket.pool):
                entry = _sideline_entry(ticket)
                return _persist_ticket_entry(
                    out_dir,
                    entry,
                    _attempt_from_entry(
                        entry, revision=revision, session_id=sess_map.get(ticket.defectId)
                    ),
                    already_locked=locked,
                )
            routed = route_ticket(ticket, match_by_id.get(ticket.defectId))
            entry: dict[str, Any] = {
                "defectId": ticket.defectId,
                "ticket": slice_ticket(ticket),
                **routed,
            }
            snapshot = capture_workspace(Path(work_dir))
            analyze_session: Optional[str] = None
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
                        resume_session_id=sess_map.get(ticket.defectId),
                    )
                )
                entry.update(result.payload)
                analyze_sources.append(result.source)
                analyze_session = result.session_id
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
            entry = _persist_candidate_snippets(Path(work_dir), entry)

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

            drifted = bool(
                snapshot.contentDigest
                and workspace_digest(Path(work_dir)) != snapshot.contentDigest
            )
            if drifted:
                loc = dict(entry.get("localization") or {})
                loc["notes"] = "; ".join(
                    x
                    for x in [loc.get("notes"), "source changed after analyze; refuse edit"]
                    if x
                )
                entry["localization"] = loc
            ctx = _verify_current_code(
                _context_with_analysis(
                    build_task_context(
                        ticket,
                        code_knowledge,
                        revision=revision,
                        snapshot=snapshot,
                        generate_patch=want_fix,
                    ),
                    entry,
                ),
                Path(work_dir),
                entry,
            )
            decision = _decision_from_entry(entry, ctx)
            gate_errors = validate_edit_decision(ctx, decision)
            if drifted:
                gate_errors = list(gate_errors) + ["source changed after analyze"]
            if gate_errors:
                decision = EditDecision.model_validate(
                    {
                        **decision.model_dump(),
                        "allowed": False,
                        "reason": "; ".join(gate_errors),
                    }
                )
            else:
                decision = EditDecision.model_validate(
                    {**decision.model_dump(), "allowed": True}
                )
            session_id = analyze_session or sess_map.get(ticket.defectId)
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
            return _persist_ticket_entry(out_dir, entry, attempt, already_locked=locked)

        for t in defect_batch.tickets:
            if wanted is not None and t.defectId not in wanted:
                continue
            try:
                tickets.append(_one(t))
            except Exception as err:  # noqa: BLE001
                failed = _exception_entry(t, err)
                tickets.append(
                    _persist_ticket_entry(
                        out_dir,
                        failed,
                        _attempt_from_entry(
                            failed,
                            revision=rev_map.get(t.defectId),
                            session_id=sess_map.get(t.defectId),
                        ),
                        already_locked=locked,
                    )
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


def _promote_after_revision(
    ticket: BatchTicket, revision: Optional[InputRevision]
) -> BatchTicket:
    """用户补充后重新评估 needs_info，不再用原 pool 永久阻断分析。"""
    if revision is None or ticket.pool != "needs_info":
        return ticket
    filled = bool(
        (ticket.observed or "").strip()
        or (ticket.expected or "").strip()
        or (ticket.steps or "").strip()
        or (revision.observed or "").strip()
    )
    if not filled:
        return ticket
    return ticket.model_copy(update={"pool": "strict"})


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


def _verify_current_code(
    context: TaskContext, work_dir: Path, entry: dict[str, Any]
) -> TaskContext:
    """按 repoPath 读候选文件；仅当机制/符号出现在正文中才记 valid。"""
    extra = list(context.evidence)
    seen = {e.evidenceId for e in extra}
    loc = entry.get("localization") or {}
    root = entry.get("rootCause") or {}
    proposed = entry.get("proposedFix") or {}
    for i, cand in enumerate(loc.get("candidates") or [], start=1):
        if not isinstance(cand, dict) or not cand.get("path"):
            continue
        path = _resolve_candidate_file(work_dir, cand)
        eid = f"read-{entry.get('defectId')}-{i}"
        if eid in seen:
            continue
        if not path.is_file():
            extra.append(
                Evidence(
                    evidenceId=eid,
                    category="code_observation",
                    source="read",
                    summary=f"missing {cand.get('repoPath') or '.'}/{cand['path']}",
                    path=str(cand["path"]),
                    repoId=str(cand.get("repoPath") or "."),
                    validity="invalid",
                )
            )
            seen.add(eid)
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        symbol = str(cand.get("symbol") or "").strip()
        tokens = _mechanism_tokens(
            " ".join(
                part
                for part in [symbol, str(root.get("summary") or ""), str(proposed.get("summary") or "")]
                if part
            )
        )
        mechanical = bool(symbol and symbol in body) or any(tok in body for tok in tokens)
        cited = str(cand.get("snippet") or cand.get("excerpt") or "").strip()
        extracted = str(cand.get("snippetSource") or "").strip().lower() == "extracted"
        why = str(cand.get("why") or "").strip()
        confirmed = bool(cited and cited in body and not extracted)
        causal = confirmed or bool(why and len(why) >= 16 and why in body)
        extra.append(
            Evidence(
                evidenceId=eid,
                category="code_observation",
                source="read",
                summary=(
                    f"mechanism fragment in {path.as_posix()}: {cited[:80] or why[:80]}"
                    if causal
                    else (
                        f"locator {symbol or ' '.join(tokens[:3])} in {cand['path']}"
                        if mechanical
                        else f"file exists but mechanism not in {cand['path']}"
                    )
                ),
                path=str(cand["path"]),
                repoId=str(cand.get("repoPath") or "."),
                validity="valid" if causal else "pending_review",
            )
        )
        seen.add(eid)
    return context.model_copy(update={"evidence": extra})


def _resolve_candidate_file(work_dir: Path, cand: dict[str, Any]) -> Path:
    rel = str(cand.get("path") or "").replace("\\", "/").lstrip("/")
    repo = str(cand.get("repoPath") or ".").replace("\\", "/").strip() or "."
    if repo in {".", ""}:
        return Path(work_dir) / rel
    return Path(work_dir) / repo / rel


def _mechanism_tokens(text: str) -> list[str]:
    return [tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", text or "")]


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
        allowed=False,
        behaviorTarget=behavior,
        codeAssociation=association,
        mechanism=summary or "unspecified",
        editRationale=rationale,
        evidenceRefs=[e.evidenceId for e in context.evidence if e.validity == "valid"],
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
    session_id: Optional[str],
) -> tuple[AttemptRecord, dict[str, Any]]:
    last_payload: dict[str, Any] = {}
    attempt_id = uuid4().hex[:12]
    state: dict[str, Any] = {"wt": None, "n": 0}
    previous = load_latest_attempt(Path(out_dir), ticket.defectId) if out_dir else None

    def edit(ctx: TaskContext, _decision: EditDecision) -> dict[str, Any]:
        if state["wt"] is None:
            dest = Path(out_dir or work_dir) / ".bugfix" / "worktrees" / ticket.defectId
            state["wt"] = prepare_workspace(snapshot, dest)
        wt = Path(state["wt"])
        state["n"] += 1
        analysis = dict(entry)
        if ctx.hypotheses:
            analysis["retryFeedback"] = [h.claim for h in ctx.hypotheses]
        result = fixer(
            FixRequest(
                work_dir=work_dir,
                ticket=ticket,
                analysis=analysis,
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
        collected = collect_patch(
            snapshot,
            wt,
            archive_dir=archive_root,
            namespace=f"{ticket.defectId}/{attempt_id}/{state['n']}",
        )
        collected = _bind_previous_patch(
            collected,
            previous,
            snapshot,
            Path(work_dir),
            revision,
            out_dir=out_dir,
        )
        diffs: list[str] = []
        for item in collected.patches:
            path = Path(item.archivePath)
            if path.is_file():
                diffs.append(path.read_text(encoding="utf-8", errors="replace"))
        return {"diff": "\n".join(diffs), "patchSet": collected}

    def check(_ctx: TaskContext, _decision: EditDecision, patch: Any) -> list[VerificationRun]:
        specs = [
            spec
            for spec in list((entry.get("suggestedVerify") or {}).get("commands") or [])
            if isinstance(spec, dict) and spec.get("command")
        ]
        wt = Path(state["wt"] or work_dir)
        digest = _patchset_digest(patch)
        if not specs:
            return [
                VerificationRun(
                    command=["suggested-verify"],
                    cwd=str(wt),
                    result="not_run",
                    coverage="suggested_only",
                    candidateDigest=digest,
                )
            ]
        log_dir = None
        if out_dir:
            log_dir = (
                Path(out_dir)
                / "defects"
                / ticket.defectId
                / "attempts"
                / attempt_id
                / "checks"
            )
        runs: list[VerificationRun] = []
        for spec in specs:
            run = run_check(spec, wt, log_dir=log_dir)
            if digest:
                run = run.model_copy(update={"candidateDigest": digest})
            runs.append(run)
        return runs

    def review(_diff: str, _ctx: TaskContext, _decision: EditDecision) -> str:
        return str(
            last_payload.get("semanticReview")
            or last_payload.get("reviewConclusion")
            or ""
        ).strip()

    attempt = run_ticket(
        context,
        {
            "analyze": lambda _ctx: decision,
            "edit": edit,
            "check": check,
            "review": review,
        },
        attempt_id=attempt_id,
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
            None if attempt.editDecision is None else attempt.editDecision.executionPremise,
        ]
        if x
    )
    entry["localization"] = loc
    if attempt.resolution == "patch_produced" and attempt.patchSet and attempt.patchSet.patches:
        entry["outcome"] = "patch_ready"
        files = [p.path for p in attempt.patchSet.patches]
        bundle = attempt.patchSet.bundlePath or attempt.patchSet.patches[0].archivePath
        entry["patch"] = {
            "path": bundle,
            "summary": "; ".join(
                x
                for x in [
                    attempt.patchSet.summary,
                    "apply order: " + ", ".join(files),
                ]
                if x
            ),
        }
        entry["blockers"] = None
        proposed = dict(entry.get("proposedFix") or {})
        if not proposed.get("summary"):
            proposed["summary"] = entry["patch"].get("summary") or "candidate patch"
        proposed["targetFiles"] = files
        proposed.setdefault("steps", [])
        entry["proposedFix"] = proposed
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
    entry = _attach_checks_to_entry(entry, attempt)
    return attempt, entry


def _bind_previous_patch(
    collected: PatchSet,
    previous: Optional[AttemptRecord],
    snapshot: Any,
    work_dir: Path,
    revision: Optional[InputRevision],
    out_dir: Optional[str] = None,
) -> PatchSet:
    """未应用且内容确认无关时才标替代；部分应用/未知只记录当前快照基线。"""
    digest = collected.baselineDigest or getattr(snapshot, "contentDigest", None)
    if digest and not collected.baselineDigest:
        collected = collected.model_copy(update={"baselineDigest": digest})
    if previous is None or previous.patchSet is None:
        return collected
    old_id = previous.patchSet.patchSetId
    state = classify_patch_state(previous.patchSet, snapshot, work_dir)
    application = str(state.get("application") or "unknown")
    feedback_app = _feedback_application(out_dir, previous.defectId, revision)
    if application == "applied":
        note = "; ".join(
            x
            for x in [
                collected.summary,
                f"incremental on applied {old_id}",
                f"snapshot {digest}" if digest else "",
            ]
            if x
        )
        return collected.model_copy(update={"summary": note, "replaces": None})
    if feedback_app == "not_applied" and application == "unknown":
        note = "; ".join(x for x in [collected.summary, f"replacement of unused {old_id}"] if x)
        return collected.model_copy(update={"replaces": old_id, "summary": note})
    note = "; ".join(
        x
        for x in [
            collected.summary,
            f"relative to current snapshot {digest}" if digest else "relative to current tree",
            f"prior {old_id} is {application}; not a full replacement",
        ]
        if x
    )
    return collected.model_copy(update={"replaces": None, "summary": note})


def _feedback_application(
    out_dir: Optional[str],
    defect_id: str,
    revision: Optional[InputRevision],
) -> str | None:
    if not out_dir:
        return None
    folder = Path(out_dir) / "defects" / defect_id / "feedback"
    if not folder.is_dir():
        return None
    wanted = revision.revisionId if revision is not None else None
    chosen: dict[str, Any] | None = None
    for path in sorted(folder.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rid = str((payload.get("revision") or {}).get("revisionId") or "")
        if wanted and rid == wanted:
            chosen = payload
            break
        chosen = payload
    if not chosen:
        return None
    raw = (chosen.get("feedback") or {}).get("application")
    return str(raw) if raw else None


def _attach_checks_to_entry(entry: dict[str, Any], attempt: AttemptRecord) -> dict[str, Any]:
    verify = dict(entry.get("suggestedVerify") or {})
    commands = []
    for run in attempt.checks:
        commands.append(
            {
                "command": list(run.command),
                "result": run.result,
                "coverage": run.coverage,
                "logRef": run.logRef,
                "cwd": run.cwd,
                "exitCode": run.exitCode,
                "candidateDigest": run.candidateDigest,
            }
        )
    if commands:
        verify["commands"] = commands
        verify["executed"] = any(c.get("result") in {"passed", "failed", "blocked"} for c in commands)
    verify.setdefault("steps", [])
    entry["suggestedVerify"] = verify
    final_digest = _patchset_digest(attempt.patchSet)
    current = [
        c
        for c in commands
        if final_digest and c.get("candidateDigest") == final_digest
    ]
    applicable = [
        c for c in current if c.get("result") in {"passed", "failed", "blocked"}
    ]
    if not applicable:
        entry["verifyStatus"] = "skipped"
    elif any(c.get("result") in {"failed", "blocked"} for c in applicable):
        entry["verifyStatus"] = "failed"
    elif all(c.get("result") == "passed" for c in applicable):
        entry["verifyStatus"] = "passed"
    else:
        entry["verifyStatus"] = "skipped"
    return entry


def _patchset_digest(patch: Any) -> str | None:
    items = list(getattr(patch, "patches", None) or [])
    if not items:
        return None
    h = hashlib.sha256()
    for item in sorted(items, key=lambda p: getattr(p, "path", "") or ""):
        h.update(str(getattr(item, "path", "")).encode("utf-8"))
        h.update(str(getattr(item, "digest", "")).encode("utf-8"))
        h.update(str(getattr(item, "kind", "")).encode("utf-8"))
    return h.hexdigest()[:16]


def _persist_candidate_snippets(work_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    loc = dict(entry.get("localization") or {})
    filled: list[dict[str, Any]] = []
    for cand in loc.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        item = dict(cand)
        cited = str(item.get("snippet") or item.get("excerpt") or "").strip()
        path = _resolve_candidate_file(work_dir, item)
        if not cited and path.is_file():
            body = path.read_text(encoding="utf-8", errors="replace")
            symbol = str(item.get("symbol") or "").strip()
            frag = _fragment_around_symbol(body, symbol)
            if frag:
                item["snippet"] = frag
                item["snippetSource"] = "extracted"
        elif cited:
            item["snippet"] = cited
        filled.append(item)
    loc["candidates"] = filled
    entry["localization"] = loc
    return entry


def _fragment_around_symbol(body: str, symbol: str, window: int = 8) -> str:
    if not symbol:
        return ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if symbol not in line:
            continue
        chunk = [ln for ln in lines[i : i + window] if ln.strip()]
        return "\n".join(chunk).strip()[:400]
    return ""


def _exception_entry(ticket: BatchTicket, err: BaseException) -> dict[str, Any]:
    detail = f"{type(err).__name__}: {err}"
    return {
        "defectId": ticket.defectId,
        "ticket": slice_ticket(ticket),
        "outcome": "other_blocked",
        "proposedFix": None,
        "patch": None,
        "blockers": {"kind": "other_blocked", "detail": detail},
        "rootCause": {
            "summary": "Agent-3 ticket failed in isolation",
            "ruledOut": [],
            "openQuestions": [detail],
        },
        "localization": {"candidates": [], "notes": detail},
        "suggestedVerify": {"steps": [], "executed": False},
        "confidence": "low",
        "verifyStatus": "skipped",
    }


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
