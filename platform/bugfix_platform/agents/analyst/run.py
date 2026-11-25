from __future__ import annotations

import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from bugfix_platform.agents.analyst.attempt_store import store_lock
from bugfix_contracts import ANALYSIS_REPORT_SCHEMA_VERSION, AnalysisReport, CodeKnowledge, DefectBatch, validate_analysis_report
from bugfix_contracts.repair import InputRevision
from bugfix_platform.sdk.analyze import AnalyzeRunner, analyze_mode_from_env, create_analyze_runner
from bugfix_platform.sdk.codegraph import ensure_codegraph
from bugfix_platform.sdk.fix import FixRunner, apply_fix_from_env, create_fix_runner
from bugfix_platform.sdk.project_mcp import load_project_mcp
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.skill_inject import discover_analyze_skills, discover_fix_skills, load_repair_skill
from bugfix_platform.agents.analyst.attempt import (
    TicketAttemptInputs, _attempt_from_entry, _exception_entry, _persist_ticket_entry,
    _ticket_with_revision, _write_markdown_report, run_ticket_attempt,
)


def run_analyst(
    *,
    work_dir: str | Path,
    defect_batch: DefectBatch,
    code_knowledge: CodeKnowledge,
    open_mr: bool = False,
    apply_fix: Optional[bool] = None,
    analyze_mode: Optional[str] = None,
    extra_skill_dirs: Optional[Sequence[str | Path]] = None,
    agent3_mcp_tools: Sequence[str] = (),
    project_integrations: bool = False,
    repair_skill_path: str | Path | None = None,
    analyze_fn: Optional[AnalyzeRunner] = None,
    fix_fn: Optional[FixRunner] = None,
    analyze_limit: Optional[int] = None,
    artifact_dir: Optional[str | Path] = None,
    ticket_ids: Optional[Sequence[str]] = None,
    revisions: Optional[Mapping[str, InputRevision]] = None,
    session_ids: Optional[Mapping[str, str]] = None,
    parent_attempt_ids: Optional[Mapping[str, str]] = None,
    already_locked: bool = False,
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
        agent3_mcp_tools: 本次允许的业务 MCP 工具全名，按仓内 .mcp.json 查找服务器。
        analyze_fn: 可注入的 ``AnalyzeRunner``（测试用）。
        fix_fn: 可注入的 ``FixRunner``（测试用）。
        analyze_limit: 最多 analyze 几张票。
        artifact_dir: patch 文件目录（缺省 ``workDir/.bugfix/patches``）。
        ticket_ids: 若给出则只处理这些缺陷。
        revisions: 票 ID → 补充 InputRevision。
        session_ids: 票 ID → 续接会话。
        already_locked: 调用方持有产物根锁，并负责发布汇总 Markdown。

    Returns:
        通过 ``validate_analysis_report`` 的 ``AnalysisReport``。
    """
    from bugfix_platform.sdk.runtime_profile import runtime_profile, skill_discovery
    work_dir = str(work_dir)
    want_fix = apply_fix_from_env(apply_fix)
    project_mcp = load_project_mcp(work_dir, code_knowledge.repoRoots, agent3_mcp_tools, full_access=project_integrations)
    repair_skill = load_repair_skill(repair_skill_path) if repair_skill_path is not None else None
    mode = analyze_mode_from_env(analyze_mode if analyze_mode is not None or repair_skill is None else "sdk")
    if repair_skill is not None and (mode != "sdk" or (analyze_fn is None and not has_credentials())):
        raise ValueError("repair_skill requires Agent3 SDK mode and model credentials")
    match_by_id = {m.defectId: m for m in code_knowledge.defectCodeMatches}
    injected = discover_analyze_skills(
        work_dir,
        repo_roots=code_knowledge.repoRoots,
        extra_dirs=extra_skill_dirs,
    )
    bound_skills = list(dict.fromkeys(s.name for s in injected))[:40]
    runner = analyze_fn or create_analyze_runner(mode)
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
    wanted = {str(x) for x in ticket_ids} if ticket_ids is not None else None
    rev_map = dict(revisions or {})
    sess_map = dict(session_ids or {})
    parent_map = dict(parent_attempt_ids or {})
    locked = bool(out_dir)
    lock_cm = store_lock(Path(out_dir)) if out_dir and not already_locked else nullcontext()

    with lock_cm:
        tickets: list[dict[str, Any]] = []
        analyze_sources: list[str] = []
        skill_reads: set[str] = set()

        inputs = TicketAttemptInputs(
            work_dir=work_dir, out_dir=out_dir, locked=locked,
            revisions=rev_map, sessions=sess_map, parents=parent_map,
            matches=match_by_id, knowledge=code_knowledge, runner=runner,
            injected=injected, codegraph=cg_status, want_fix=want_fix,
            project_mcp=project_mcp,
            repair_skill=repair_skill,
            fixer=fixer, fix_fn=fix_fn, fix_skills=fix_skills, remaining=remaining,
            analyze_sources=analyze_sources, skill_reads=skill_reads,
        )

        for t in defect_batch.tickets:
            if wanted is not None and t.defectId not in wanted:
                continue
            try:
                tickets.append(run_ticket_attempt(t, inputs))
            except Exception as err:  # noqa: BLE001
                failed = _exception_entry(_ticket_with_revision(t, rev_map.get(t.defectId)), err)
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

        skill_details = skill_discovery(work_dir, code_knowledge.repoRoots, injected, skill_reads)
        if repair_skill is not None:
            skill_details.append({
                "source": "user_repair", "name": repair_skill.name,
                "path": str(repair_skill.skill_md), "selected": True,
                "applied": False, "reason": "required in SDK prompts; application not independently verified",
            })
        report = {
            "runtimeProfile": runtime_profile().model_dump(),
            "skillDiscovery": skill_details,
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
        if out_dir and not already_locked:
            _write_markdown_report(out_dir, defect_batch.productLine, tickets)
        return validate_analysis_report(report)


def _limit_from_env() -> Optional[int]:
    import os

    raw = os.environ.get("BUGFIX_ANALYZE_LIMIT")
    if raw is None or raw.strip() == "":
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None
