"""CLI 入口（``bugfix-agent`` console script）。

子命令
------
- ``prepare-batch``：只跑 Agent-1 → defect-batch JSON（不走父图）。
- ``run``：完整 Agent-1→2→3（``run_three_agent_workflow``）；``--out-dir``
  开启渐进产物落盘。
- ``serve``：回环上的 FastAPI S4 壳。
- ``version``：打印包版本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bugfix_agent.workflow import run_three_agent_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bugfix-agent", description="Three-agent defect workflow (Python)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run Agent-1→2→3 workflow")
    run_p.add_argument("--work-dir", required=True)
    run_p.add_argument("--product-line", required=True)
    run_p.add_argument(
        "--source",
        required=True,
        help="raw-defects JSON, or platform 缺陷拉取 CSV (defectTitle/describle/…)",
    )

    prep = sub.add_parser("prepare-batch", help="Agent-1 only: ingest → defect-batch.json")
    prep.add_argument("--product-line", required=True)
    prep.add_argument("--source", required=True, help="JSON or platform CSV")
    prep.add_argument("--posture", choices=["alpha", "beta"], default="beta")
    prep.add_argument("--out", required=True, help="Write defect-batch JSON")
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
    run_p.add_argument("--out-dir", default=None, help="Write artifacts JSON here")

    serve_p = sub.add_parser("serve", help="HTTP API (S4 FastAPI): POST/GET /v1/runs")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8787)

    ver = sub.add_parser("version")
    ver.set_defaults(cmd="version")

    args = parser.parse_args(argv)
    if args.cmd == "version":
        from bugfix_agent import __version__

        print(__version__)
        return 0

    if args.cmd == "serve":
        from bugfix_agent.http.app import run_server

        run_server(host=args.host, port=args.port)
        return 0

    if args.cmd == "prepare-batch":
        from bugfix_agent.defect_batch import run_defect_batch_prepare

        batch = run_defect_batch_prepare(
            product_line=args.product_line,
            source=args.source,
            posture=args.posture,
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"ok": True, "tickets": len(batch.tickets), "funnel": batch.funnel, "out": str(out)},
                ensure_ascii=False,
            )
        )
        return 0

    result = run_three_agent_workflow(
        work_dir=args.work_dir,
        product_line=args.product_line,
        source=args.source,
        posture=args.posture,
        open_mr=args.open_mr,
        skip_agent2=args.skip_agent2,
        skip_agent3=args.skip_agent3,
        analyze_mode=args.analyze_mode,
        cartography_mode=args.cartography_mode,
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
