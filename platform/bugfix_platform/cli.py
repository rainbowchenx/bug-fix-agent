"""平台 CLI（``bugfix-platform`` console script）。

子命令
------
- ``run``：LangGraph Agent-2→3（需要已有 ``--defect-batch``）。
- ``feedback``：把用户反馈 JSON 导入产物根（不自动开下一轮）。
- ``resume``：按已落盘 attempt / revision 决定续接或新开。
- ``serve``：回环上的 FastAPI S4 壳。
- ``version``：打印包版本。

Agent-1 的 ``prepare-batch`` / ``apply-review`` 在 ``bugfix-agent``，不在这里。
"""

from __future__ import annotations

from bugfix_contracts.env import load_env_file

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _cmd_feedback(root: str, file: str) -> int:
    """导入一份反馈 JSON，按 feedbackId 幂等。"""
    from bugfix_contracts.repair import Feedback
    from bugfix_platform.agents.analyst.feedback import import_feedback

    payload = json.loads(Path(file).read_text(encoding="utf-8"))
    revision = import_feedback(Path(root), Feedback.model_validate(payload))
    print(json.dumps(revision.model_dump(), ensure_ascii=False, indent=2))
    return 0


def _cmd_resume(
    root: str,
    defect_id: str,
    revision_id: str | None,
    apply_fix: bool = False,
) -> int:
    """写出 session-decision.json；``--apply-fix`` 时跑下一轮分析/编辑。"""
    from bugfix_contracts.analysis_report import validate_analysis_report
    from bugfix_contracts.code_knowledge import validate_code_knowledge
    from bugfix_contracts.defect_batch import load_defect_batch
    from bugfix_platform.agents.analyst.run import run_analyst
    from bugfix_platform.agents.analyst.sessions import load_revision, resume_from_store

    base = Path(root)
    decision = resume_from_store(base, defect_id, revision_id)
    print(
        json.dumps(
            {
                "action": decision.action,
                "sessionId": decision.sessionId,
                "reason": decision.reason,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not apply_fix:
        return 0
    batch_path = base / "defect-batch.json"
    knowledge_path = base / "code-knowledge.json"
    if not batch_path.is_file() or not knowledge_path.is_file():
        print("resume --apply-fix needs defect-batch.json and code-knowledge.json", file=sys.stderr)
        return 1
    batch = load_defect_batch(batch_path)
    knowledge = validate_code_knowledge(json.loads(knowledge_path.read_text(encoding="utf-8")))
    report_path = base / "analysis-report.json"
    work_dir = knowledge.workDir
    if report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        work_dir = str(previous.get("workDir") or work_dir)
    revision = load_revision(base, defect_id, revision_id)
    revisions = {defect_id: revision} if revision is not None else {}
    session_ids = {defect_id: decision.sessionId} if decision.sessionId else {}
    report = run_analyst(
        work_dir=work_dir,
        defect_batch=batch,
        code_knowledge=knowledge,
        apply_fix=True,
        ticket_ids=[defect_id],
        revisions=revisions,
        session_ids=session_ids,
        artifact_dir=base,
    )
    dumped = report.model_dump()
    round_dir = base / "rounds"
    round_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (round_dir / f"{defect_id}-{stamp}.json").write_text(
        json.dumps(dumped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    by_id: dict[str, object] = {}
    if report_path.is_file():
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        for item in previous.get("tickets") or []:
            if isinstance(item, dict) and item.get("defectId"):
                by_id[str(item["defectId"])] = item
    for item in dumped.get("tickets") or []:
        if isinstance(item, dict) and item.get("defectId"):
            by_id[str(item["defectId"])] = item
    merged_tickets = list(by_id.values())
    by_outcome: dict[str, int] = {}
    for item in merged_tickets:
        if not isinstance(item, dict):
            continue
        oc = str(item.get("outcome") or "other_blocked")
        by_outcome[oc] = by_outcome.get(oc, 0) + 1
    dumped["tickets"] = merged_tickets
    dumped["summary"] = {"total": len(merged_tickets), "byOutcome": by_outcome}
    report_path.write_text(
        validate_analysis_report(dumped).model_dump_json(indent=2),
        encoding="utf-8",
    )
    from bugfix_platform.agents.analyst.report import render_report

    (base / "analysis-report.md").write_text(
        render_report({"batchId": dumped.get("productLine"), "tickets": merged_tickets}),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # README 让用户 `cp .env.example .env`；不在这里读的话那个文件是摆设。
    # 已存在的环境变量优先，平台注入的值不会被仓里的 .env 覆盖。
    load_env_file()
    parser = argparse.ArgumentParser(
        prog="bugfix-platform",
        description="LangGraph Agent-2→3 (requires defect-batch from Agent-1)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser(
        "run",
        help="LangGraph Agent-2→3 (requires defect-batch from prepare-batch / skill)",
    )
    run_p.add_argument("--work-dir", required=True)
    run_p.add_argument("--product-line", required=True)
    run_p.add_argument(
        "--defect-batch",
        required=True,
        help="Path to defect-batch.json from Agent-1 prepare-batch",
    )
    run_p.add_argument("--posture", choices=["alpha", "beta"], default="beta")
    run_p.add_argument("--open-mr", action="store_true")
    run_p.add_argument(
        "--apply-fix",
        action="store_true",
        help="Agent-3: after the report, run a worktree fix session (default off)",
    )
    run_p.add_argument("--skip-agent2", action="store_true")
    run_p.add_argument("--skip-agent3", action="store_true")
    run_p.add_argument(
        "--analyze-mode",
        choices=["heuristic", "sdk"],
        default=None,
        help="Agent-3 analyze: heuristic (default without API key) or Claude Agent SDK",
    )
    run_p.add_argument(
        "--cartography-mode",
        choices=["heuristic", "sdk"],
        default=None,
        help="Agent-2 cartography enrich: heuristic or Claude Agent SDK",
    )
    run_p.add_argument(
        "--cartography-profile",
        choices=["electron_node", "micro_frontend", "device_web", "unknown"],
        default=None,
        help=(
            "Agent-2 repo type (caller-supplied; not detected). "
            "Omit to leave cartographyProfile=unknown."
        ),
    )
    run_p.add_argument(
        "--skills-dir",
        action="append",
        default=None,
        dest="skills_dirs",
        metavar="DIR",
        help=(
            "Extra Agent-2/3 overlay skill root (repeatable). Merged after "
            ".claude/skills and workDir/.bugfix/skills; overlay outranks "
            "package SOP. Also reads BUGFIX_SKILLS_DIR."
        ),
    )
    run_p.add_argument("--out-dir", default=None, help="Write artifacts JSON here")

    fb_p = sub.add_parser(
        "feedback",
        help="Import a feedback JSON file into an artifact root (no auto-run)",
    )
    fb_p.add_argument("--root", required=True, help="Artifact / report root")
    fb_p.add_argument("--file", required=True, help="Feedback JSON file")

    resume_p = sub.add_parser(
        "resume",
        help="Choose resume/new for one defect from stored attempt + imported revision",
    )
    resume_p.add_argument("--root", required=True, help="Artifact / report root")
    resume_p.add_argument("--defect-id", required=True)
    resume_p.add_argument(
        "--revision-id",
        default=None,
        help="Imported InputRevision id; omit to use the latest feedback file",
    )
    resume_p.add_argument(
        "--apply-fix",
        action="store_true",
        help="Run the next analyze/edit/check turn after writing the session decision",
    )

    serve_p = sub.add_parser("serve", help="HTTP API (S4 FastAPI): POST/GET /v1/runs")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8787)

    ver = sub.add_parser("version")
    ver.set_defaults(cmd="version")

    args = parser.parse_args(argv)
    if args.cmd == "version":
        from bugfix_platform import __version__

        print(__version__)
        return 0

    if args.cmd == "serve":
        from bugfix_platform.http.app import run_server

        run_server(host=args.host, port=args.port)
        return 0

    if args.cmd == "feedback":
        return _cmd_feedback(args.root, args.file)

    if args.cmd == "resume":
        return _cmd_resume(
            args.root,
            args.defect_id,
            args.revision_id,
            apply_fix=bool(getattr(args, "apply_fix", False)),
        )

    if args.cmd != "run":  # pragma: no cover
        raise SystemExit(f"unknown command: {args.cmd}")

    from bugfix_platform.workflow import run_three_agent_workflow

    result = run_three_agent_workflow(
        work_dir=args.work_dir,
        product_line=args.product_line,
        defect_batch=args.defect_batch,
        posture=args.posture,
        open_mr=args.open_mr,
        apply_fix=True if args.apply_fix else None,
        skip_agent2=args.skip_agent2,
        skip_agent3=args.skip_agent3,
        analyze_mode=args.analyze_mode,
        cartography_mode=args.cartography_mode,
        cartography_profile=args.cartography_profile,
        extra_skill_dirs=args.skills_dirs,
        artifact_dir=args.out_dir,
    )
    payload = {
        "ok": result.ok,
        "stage": result.stage,
        "error": result.error,
        "funnel": result.artifacts.defect_batch.funnel if result.artifacts.defect_batch else None,
        "profile": (
            result.artifacts.code_knowledge.cartographyProfile
            if result.artifacts.code_knowledge
            else None
        ),
        "summary": (
            result.artifacts.analysis_report.summary.model_dump()
            if result.artifacts.analysis_report and result.artifacts.analysis_report.summary
            else None
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        if result.artifacts.defect_batch:
            (out / "defect-batch.json").write_text(
                result.artifacts.defect_batch.model_dump_json(indent=2), encoding="utf-8"
            )
        if result.artifacts.code_knowledge:
            (out / "code-knowledge.json").write_text(
                result.artifacts.code_knowledge.model_dump_json(indent=2), encoding="utf-8"
            )
        if result.artifacts.analysis_report:
            (out / "analysis-report.json").write_text(
                result.artifacts.analysis_report.model_dump_json(indent=2), encoding="utf-8"
            )

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
