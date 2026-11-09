"""CLI 入口（``bugfix-agent`` console script）。

子命令
------
- ``prepare-batch``：Agent-1（图外）→ defect-batch JSON；供 skill / Claude Code 使用。
- ``apply-review``：把意图复核调整写回已有 defect-batch（重建簇后校验）。
- ``run``：LangGraph Agent-2→3（``run_three_agent_workflow``）；需要已有
  ``--defect-batch``；``--out-dir`` 开启渐进产物落盘。
- ``serve``：回环上的 FastAPI S4 壳。
- ``preflight``：Agent-1 Step 0 列映射体检（图外）。
- ``xlsx-to-raw``：Excel 导出 → raw-defects JSON（图外）。
- ``self-check``：打印构建来源（exe 里还校验 vendored 副本哈希）。
- ``version``：打印包版本。

``run`` / ``serve`` 依赖 ``workflow`` 与 ``http``，``main(standalone=True)`` 时
不注册——独立 exe 只带 Agent-1，不该列出跑不了的子命令。langgraph 也一律
懒加载，``import bugfix_agent.cli`` 不会把它拖进来。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path



# 这三个子命令的外部参数各自独立（preflight 有 --sheet/--encoding，
# xlsx-to-raw 有 --xlsx/--limit），与其在 cli 里再抄一份 argparse，
# 不如把剩余参数原样交给它们自己的 main()。
_PASSTHROUGH = ("preflight", "xlsx-to-raw")


def _run_passthrough(name: str, rest: list[str]) -> int:
    if name == "preflight":
        from bugfix_agent.ingest.preflight import main as target
    else:
        from bugfix_agent.ingest.xlsx_source import main as target
    saved = sys.argv
    sys.argv = [name, *rest]
    try:
        target()
    finally:
        sys.argv = saved
    return 0


def _manifest_path() -> Path:
    """``VENDOR.json`` 的位置：onefile 打包后在 ``_MEIPASS``，源码树里在包的上层。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "VENDOR.json"
    return Path(__file__).resolve().parents[1] / "VENDOR.json"


def _cmd_self_check() -> int:
    """打印这份构建的来源；能读到 VENDOR.json 时再逐文件校验哈希。"""
    from bugfix_agent import __version__

    path = _manifest_path()
    if not path.exists():
        print(f"version      : {__version__}")
        print("build        : source checkout / installed package (no VENDOR.json)")
        return 0

    manifest = json.loads(path.read_text(encoding="utf-8"))
    print(f"vendor files : {len(manifest['files'])}")
    print(f"source       : {manifest['source']}")
    print(f"commit       : {manifest['commit']}")
    print(f"copiedAt     : {manifest['copiedAt']}")
    if getattr(sys, "frozen", False):
        # onefile 的源码在归档里，运行时拿不到文件比哈希。
        print("mode         : frozen single-file build (hashes not verifiable at runtime)")
        return 0

    root = path.parent
    bad = [rel for rel, want in manifest["files"].items()
           if (root / rel).exists() and hashlib.sha256((root / rel).read_bytes()).hexdigest() != want]
    missing = [rel for rel in manifest["files"] if not (root / rel).exists()]
    for rel in missing:
        print(f"  MISSING  {rel}")
    for rel in bad:
        print(f"  CHANGED  {rel}")
    if missing or bad:
        return 1
    print("  OK  all hashes match")
    return 0


def _add_platform_parsers(sub: argparse._SubParsersAction) -> None:
    """注册依赖 workflow / http 的子命令（``standalone`` 构建里不挂）。"""
    run_p = sub.add_parser(
        "run",
        help="LangGraph Agent-2→3 (requires defect-batch from prepare-batch / skill)",
    )
    run_p.add_argument("--work-dir", required=True)
    run_p.add_argument("--product-line", required=True)
    run_p.add_argument(
        "--defect-batch",
        required=True,
        help="Path to defect-batch.json from prepare-batch / defect-batch-prepare skill",
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



def main(argv: list[str] | None = None, *, standalone: bool = False) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in _PASSTHROUGH:
        return _run_passthrough(raw[0], raw[1:])

    parser = argparse.ArgumentParser(
        prog="bugfix-agent",
        description="Defect workflow: Agent-1 outside LangGraph; Agent-2→3 via LangGraph",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser(
        "prepare-batch",
        help="Agent-1 only (outside LangGraph): ingest → defect-batch.json",
    )
    prep.add_argument("--product-line", required=True)
    prep.add_argument("--source", required=True, help="JSON or platform CSV")
    prep.add_argument("--posture", choices=["alpha", "beta"], default="beta")
    prep.add_argument("--out", required=True, help="Write defect-batch JSON")

    review = sub.add_parser(
        "apply-review",
        help="Apply intent-review overrides onto an existing defect-batch.json",
    )
    review.add_argument("--batch", required=True, help="Existing defect-batch JSON")
    review.add_argument("--overrides", required=True, help="JSON {adjustments: [...]}")
    review.add_argument("--out", required=True, help="Write updated defect-batch JSON")

    if not standalone:
        _add_platform_parsers(sub)

    pre = sub.add_parser(
        "preflight",
        help="Agent-1 Step 0: column-mapping health check (outside LangGraph)",
    )

    xl = sub.add_parser(
        "xlsx-to-raw",
        help="Excel export → raw-defects JSON (outside LangGraph)",
    )

    chk = sub.add_parser(
        "self-check",
        help="Print build provenance; verify vendored hashes when available",
    )

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

    if args.cmd == "apply-review":
        from bugfix_agent.defect_batch.review import IntentReviewFile, apply_intent_review
        from bugfix_agent.contracts.defect_batch import load_defect_batch

        batch = load_defect_batch(args.batch)
        payload = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        review_file = IntentReviewFile.model_validate(payload)
        updated = apply_intent_review(batch, review_file.adjustments)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "tickets": len(updated.tickets),
                    "funnel": updated.funnel,
                    "adjustments": len(review_file.adjustments),
                    "out": str(out),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "self-check":
        return _cmd_self_check()

    if args.cmd != "run":  # pragma: no cover - argparse 已经限定了取值
        raise SystemExit(f"unknown command: {args.cmd}")

    from bugfix_agent.workflow import run_three_agent_workflow

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
