from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import uuid4

from bugfix_platform.agents.analyst.attempt_store import AttemptStoreBusy, save_attempt
from bugfix_platform.agents.analyst.report import render_report
from bugfix_platform.agents.analyst.route import route_ticket, slice_ticket
from bugfix_contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    is_match_pool,
    validate_analysis_report,
)
from bugfix_contracts.analysis_report import TicketReport
from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord
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
    ensure_ticket_worktree,
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
) -> AnalysisReport:
    """Agent-3 公开入口：产出 ``analysis-report``（默认只出报告、不改码）。

    对匹配池中的每张票::

        route_ticket（确定性 hint）──► analyze 会话（needs_info 除外）
                                  └──► ``apply_fix`` 时可选 fix 会话

    - ``needs_ticket_info`` 停在路由器（不调 LLM）。
    - 空候选仍进 analyze（软起点；D4）。
    - ``apply_fix`` 默认关：可修票也是 ``plan_only``。
    - 单票校验失败 → ``other_blocked``，整份报告仍继续。
    - ``open_mr`` 只记录请求标志；没有真实 ``mrUrl`` 时 ``integrateMode`` 仍为 ``none``。

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

    tickets: list[dict[str, Any]] = []
    analyze_sources: list[str] = []
    for t in defect_batch.tickets:
        if not is_match_pool(t.pool):
            tickets.append(_persist_ticket_entry(out_dir, _sideline_entry(t)))
            continue
        routed = route_ticket(t, match_by_id.get(t.defectId))
        entry: dict[str, Any] = {
            "defectId": t.defectId,
            "ticket": slice_ticket(t),
            **routed,
        }

        if routed["outcome"] != "needs_ticket_info" and (
            remaining is None or remaining > 0
        ):
            result = runner(
                AnalyzeRequest(
                    work_dir=work_dir,
                    ticket=t,
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

        if want_fix and fixer is not None and _actionable_for_fix(entry):
            if fix_fn is not None:
                wt_path: str | None = work_dir
                wt_err = None
            else:
                wt, wt_err = ensure_ticket_worktree(work_dir, t.defectId)
                wt_path = str(wt) if wt is not None else None
            if wt_path is None:
                loc = dict(entry.get("localization") or {})
                loc["notes"] = "; ".join(
                    x for x in [loc.get("notes"), wt_err or "worktree unavailable"] if x
                )
                entry["localization"] = loc
                entry["outcome"] = "plan_only"
                entry["patch"] = None
                entry["blockers"] = None
            else:
                fix_result = fixer(
                    FixRequest(
                        work_dir=work_dir,
                        ticket=t,
                        analysis=dict(entry),
                        worktree_path=wt_path,
                        artifact_dir=out_dir,
                        injected_skills=fix_skills,
                    )
                )
                if fix_result.payload.get("outcome") == "patch_ready":
                    entry["outcome"] = "patch_ready"
                    entry["patch"] = fix_result.payload.get("patch")
                    entry["blockers"] = None
                else:
                    loc = dict(entry.get("localization") or {})
                    loc["notes"] = "; ".join(
                        x
                        for x in [
                            loc.get("notes"),
                            f"fix={fix_result.source}",
                            fix_result.detail,
                        ]
                        if x
                    )
                    entry["localization"] = loc
                    if entry.get("outcome") == "patch_ready":
                        entry["outcome"] = "plan_only"
                        entry["patch"] = None
                        entry["blockers"] = None

        tickets.append(_persist_ticket_entry(out_dir, entry))

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


def _attempt_from_entry(entry: dict[str, Any]) -> AttemptRecord:
    outcome = str(entry.get("outcome") or "other_blocked")
    kind = str((entry.get("blockers") or {}).get("kind") or "")
    resolution = "excluded" if kind in {"excluded", "duplicate"} else _OUTCOME_RESOLUTION.get(
        outcome, "incomplete"
    )
    return AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId=uuid4().hex[:12],
        defectId=str(entry.get("defectId") or "unknown"),
        execution="completed",
        resolution=resolution,  # type: ignore[arg-type]
        patchDelivery="candidate" if outcome == "patch_ready" else "none",
    )


def _persist_ticket_entry(out_dir: Optional[str], entry: dict[str, Any]) -> dict[str, Any]:
    coerced = _coerce_ticket_entry(entry)
    if not out_dir:
        return coerced
    try:
        save_attempt(Path(out_dir), _attempt_from_entry(coerced))
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
        render_report(
            {
                "batchId": product_line,
                "tickets": [
                    {"defectId": t.get("defectId"), "outcome": t.get("outcome")}
                    for t in tickets
                ],
            }
        ),
        encoding="utf-8",
    )


def _actionable_for_fix(entry: dict[str, Any]) -> bool:
    """True when analysis has a real root cause and a proposed fix."""
    if entry.get("outcome") not in ("plan_only", "patch_ready"):
        return False
    summary = str((entry.get("rootCause") or {}).get("summary") or "").strip()
    lowered = summary.lower()
    if not summary or lowered.startswith("pending") or "analyze session skipped" in lowered:
        return False
    proposed = entry.get("proposedFix") or {}
    return bool(isinstance(proposed, dict) and proposed.get("summary"))


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
