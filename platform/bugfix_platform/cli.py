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
from pathlib import Path


def _cmd_feedback(root: str, file: str) -> int:
    from bugfix_platform.workflow.resume import import_run_feedback

    revision = import_run_feedback(Path(root), Path(file))
    print(json.dumps(revision.model_dump(), ensure_ascii=False, indent=2))
    return 0


def _cmd_resume(
    root: str,
    defect_id: str,
    revision_id: str | None,
    apply_fix: bool = False,
    execute: bool = False,
) -> int:
    from bugfix_platform.workflow.resume import (
        AttemptStoreBusy, ResumeRequestError, SessionDecision, resume_defect,
    )

    def print_decision(decision: SessionDecision) -> None:
        print(json.dumps(
            {"action": decision.action, "sessionId": decision.sessionId, "reason": decision.reason},
            ensure_ascii=False, indent=2,
        ))

    try:
        resume_defect(Path(root), defect_id, revision_id, apply_fix=apply_fix,
                      execute=execute, on_decision=print_decision)
    except (AttemptStoreBusy, ResumeRequestError) as err:
        print(str(err), file=sys.stderr)
        return 1
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
    run_p.add_argument("--resume-dir", default=None, help="Agent-2 progress journal to resume")
    run_p.add_argument("--ticket-ids", default=None, help="Comma-separated defect IDs to investigate/analyze")

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
    resume_p.add_argument("--execute", action="store_true", help="Run another report-only analysis")
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

    commit_p = sub.add_parser("commit", help="Commit a staged Agent-3 candidate locally")
    commit_p.add_argument("--root", required=True, help="Artifact / report root")
    commit_p.add_argument("--defect-id", required=True)

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

    if args.cmd == "commit":
        from bugfix_platform.workflow.commit import commit_candidate

        try:
            sha = commit_candidate(Path(args.root), args.defect_id)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps({"defectId": args.defect_id, "commitSha": sha}))
        return 0

    if args.cmd == "feedback":
        return _cmd_feedback(args.root, args.file)

    if args.cmd == "resume":
        return _cmd_resume(
            args.root,
            args.defect_id,
            args.revision_id,
            apply_fix=bool(getattr(args, "apply_fix", False)),
            execute=bool(args.execute),
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
        resume_dir=getattr(args, "resume_dir", None),
        ticket_ids=[x for x in (args.ticket_ids or "").split(",") if x] or None,
    )
    payload = {
        "ok": result.ok,
        "stage": result.stage,
        "error": result.error,
        "artifactDir": result.artifact_dir,
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

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
