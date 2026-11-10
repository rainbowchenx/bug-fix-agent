"""Agent-1 CLI（``bugfix-agent`` console script）。

子命令
------
- ``prepare-batch``：入口映射 → defect-batch JSON。
- ``apply-review``：把意图复核调整写回已有 defect-batch（重建簇后校验）。
- ``preflight``：Step 0 列映射体检。
- ``xlsx-to-raw``：Excel 导出 → raw-defects JSON。
- ``self-check``：打印构建来源（exe 里还校验 vendored 副本哈希）。
- ``version``：打印包版本。

本入口不含 ``run`` / ``serve``——那是 ``bugfix-platform`` 的事。
"""

from __future__ import annotations

from bugfix_contracts.console import force_utf8_console
from bugfix_contracts.env import load_env_file

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# 这两个子命令的外部参数各自独立，与其在 cli 里再抄一份 argparse，
# 不如把剩余参数原样交给它们自己的 main()。
_PASSTHROUGH = ("preflight", "xlsx-to-raw")


def _run_passthrough(name: str, rest: list[str]) -> int:
    if name == "preflight":
        from bugfix_agent1.ingest.preflight import main as target
    else:
        from bugfix_agent1.ingest.xlsx_source import main as target
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
    from bugfix_agent1 import __version__

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
        print("mode         : frozen single-file build (hashes not verifiable at runtime)")
        return 0

    root = path.parent
    bad = [
        rel
        for rel, want in manifest["files"].items()
        if (root / rel).exists() and hashlib.sha256((root / rel).read_bytes()).hexdigest() != want
    ]
    missing = [rel for rel in manifest["files"] if not (root / rel).exists()]
    for rel in missing:
        print(f"  MISSING  {rel}")
    for rel in bad:
        print(f"  CHANGED  {rel}")
    if missing or bad:
        return 1
    print("  OK  all hashes match")
    return 0


def _cluster_stats(batch: Any) -> dict[str, int]:
    """簇健康度的可抄数字。报告里写错簇数/单票簇数是常见事故。"""
    sizes = sorted((len(c.defectIds) for c in batch.clusters), reverse=True)
    return {
        "total": len(sizes),
        "singleton": sum(1 for s in sizes if s == 1),
        "largest": sizes[0] if sizes else 0,
    }


def _intent_transitions(before: Any, after: Any) -> dict[str, int]:
    """复核到底动了哪一类标签。

    上一轮 agent 把「36 张」拆成了「18 张 unclear 被救回」+「3 张启发式误判」，
    两句话都错：实际是 18 + 18。改池与改标签也不是一回事，分开计数。
    """
    old = {t.defectId: t for t in before.tickets}
    out = {"changedIntent": 0, "fromUnclear": 0, "fromHeuristic": 0, "fromNone": 0,
           "keptHeuristic": 0, "changedPool": 0}
    for t in after.tickets:
        prev = old.get(t.defectId)
        if prev is None:
            continue
        if prev.pool != t.pool:
            out["changedPool"] += 1
        if prev.intent != t.intent:
            out["changedIntent"] += 1
            if prev.intent is None:
                out["fromNone"] += 1
            elif prev.intentSource == "unclear":
                out["fromUnclear"] += 1
            elif prev.intentSource == "heuristic":
                out["fromHeuristic"] += 1
        elif prev.intentSource == "heuristic":
            out["keptHeuristic"] += 1
    return out


def _intent_stats(batch: Any) -> dict[str, int]:
    """按 ``intentSource`` 计数。

    报告里最容易说错的就是「改了多少张」：``unclear`` 是补空、``heuristic`` 是纠错，
    两者混在一起报，数字必然对不上。让产物自己给数。
    """
    stats: dict[str, int] = {}
    for t in batch.tickets:
        key = t.intentSource if t.intent is not None else "none"
        stats[key] = stats.get(key, 0) + 1
    return dict(sorted(stats.items()))


def main(argv: list[str] | None = None) -> int:
    # 平台按 UTF-8 读我们的输出；Windows 默认 cp936，中文和 `→` 会变乱码。
    force_utf8_console()
    # README 让用户 `cp .env.example .env`；不在这里读的话那个文件是摆设。
    # 已存在的环境变量优先，平台注入的值不会被仓里的 .env 覆盖。
    load_env_file()
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] in _PASSTHROUGH:
        return _run_passthrough(raw[0], raw[1:])

    parser = argparse.ArgumentParser(
        prog="bugfix-agent",
        description="Agent-1 (outside LangGraph): ingest → defect-batch.json",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser(
        "prepare-batch",
        help="Ingest → defect-batch.json",
    )
    prep.add_argument(
        "--product-line",
        default=None,
        help="Batch namespace / clusterId prefix. Omit to derive it from the "
        "source (project code in the filename, or productLine inside raw-defects).",
    )
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

    val = sub.add_parser(
        "validate",
        help="Re-validate a defect-batch.json and print its summary",
    )
    val.add_argument("--batch", required=True, help="defect-batch JSON to check")

    sub.add_parser(
        "preflight",
        help="Step 0: column-mapping health check",
    )
    sub.add_parser(
        "xlsx-to-raw",
        help="Excel export → raw-defects JSON",
    )
    sub.add_parser(
        "self-check",
        help="Print build provenance; verify vendored hashes when available",
    )
    ver = sub.add_parser("version")
    ver.set_defaults(cmd="version")

    args = parser.parse_args(argv)
    if args.cmd == "version":
        from bugfix_agent1 import __version__

        print(__version__)
        return 0

    if args.cmd == "validate":
        from pydantic import ValidationError

        from bugfix_contracts.defect_batch import load_defect_batch

        try:
            batch = load_defect_batch(args.batch)
        except (ValidationError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "schemaVersion": batch.schemaVersion,
                    "tickets": len(batch.tickets),
                    "funnel": batch.funnel,
                    "clusters": _cluster_stats(batch),
                    "intentSource": _intent_stats(batch),
                    "productLine": batch.productLine,
                    "posture": batch.posture,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "prepare-batch":
        from bugfix_agent1.defect_batch import run_defect_batch_prepare
        from bugfix_agent1.ingest.project import resolve_product_line

        # 先把命名空间定下来，再把出处打出来：clusterId 的前缀不该凭空出现。
        product_line, provenance = resolve_product_line(args.source, args.product_line)
        batch = run_defect_batch_prepare(
            product_line=product_line,
            source=args.source,
            posture=args.posture,
        )
        print(f"productLine: {product_line} (via {provenance})", file=sys.stderr)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "tickets": len(batch.tickets),
                    "funnel": batch.funnel,
                    "clusters": _cluster_stats(batch),
                    "intentSource": _intent_stats(batch),
                    "productLine": batch.productLine,
                    "posture": batch.posture,
                    "out": str(out),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "apply-review":
        from bugfix_agent1.defect_batch.review import IntentReviewFile, apply_intent_review
        from bugfix_contracts.defect_batch import load_defect_batch

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
                    "clusters": _cluster_stats(updated),
                    "review": _intent_transitions(batch, updated),
                    "adjustments": len(review_file.adjustments),
                    "out": str(out),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "self-check":
        return _cmd_self_check()

    raise SystemExit(f"unknown command: {args.cmd}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
