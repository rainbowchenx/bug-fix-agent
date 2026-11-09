"""平台 CLI（``bugfix-platform`` console script）。

子命令
------
- ``run``：LangGraph Agent-2→3（需要已有 ``--defect-batch``）。
- ``serve``：回环上的 FastAPI S4 壳。
- ``version``：打印包版本。

Agent-1 的 ``prepare-batch`` / ``apply-review`` 在 ``bugfix-agent``，不在这里。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
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

    if args.cmd != "run":  # pragma: no cover
        raise SystemExit(f"unknown command: {args.cmd}")

    from bugfix_platform.workflow import run_three_agent_workflow

    result = run_three_agent_workflow(
        work_dir=args.work_dir,
        product_line=args.product_line,
        defect_batch=args.defect_batch,
        posture=args.posture,
        open_mr=args.open_mr,
        skip_agent2=args.skip_agent2,
        skip_agent3=args.skip_agent3,
        analyze_mode=args.analyze_mode,
        cartography_mode=args.cartography_mode,
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
