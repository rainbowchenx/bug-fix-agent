#!/usr/bin/env python3
"""Agent-1 standalone CLI — prepare-batch / apply-review，零安装。

只用标准库 + pydantic。不导入 agents / workflow / langgraph。

    python scripts/agent1.py prepare-batch \
        --product-line PJ14PD20260423284 --source export.csv --out 01-defect-batch.rule.json

    python scripts/agent1.py apply-review \
        --batch 01-defect-batch.rule.json --overrides 02-review.json --out 03-defect-batch.json

与 `bugfix-agent prepare-batch` / `bugfix-agent apply-review` 参数和行为一致。
优先使用本目录 `_vendor/` 里的实现，保证不同机器上结果一致；
设 `AGENT1_USE_INSTALLED=1` 可改用已安装的 `bugfix_agent` 包。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Union

_SCRIPTS = Path(__file__).resolve().parent
_VENDOR = _SCRIPTS / "_vendor"
_FROZEN = bool(getattr(sys, "frozen", False))

# VENDOR.json 在源码模式与 onefile 打包后位置不同。
def _manifest_path() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "VENDOR.json"
    return _VENDOR / "VENDOR.json"

if os.environ.get("AGENT1_USE_INSTALLED") != "1" and _VENDOR.is_dir():
    # 以本目录的副本为准，避免机器上装了旧版包导致结果不一致。
    sys.path.insert(0, str(_VENDOR))

# 同目录的 preflight / xlsx 转换一并入库（纯标准库 + 延迟 import openpyxl）。
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
try:
    import preflight as _preflight
    import xlsx_to_raw_defects as _xlsx
except ImportError:  # pragma: no cover - 脚本被单独拷走时
    _preflight = None  # type: ignore[assignment]
    _xlsx = None  # type: ignore[assignment]

try:
    from bugfix_agent.contracts.defect_batch import DefectBatch, validate_defect_batch
    from bugfix_agent.defect_batch import run_defect_batch_prepare
    from bugfix_agent.defect_batch.review import IntentReviewFile, apply_intent_review
except ImportError as e:  # pragma: no cover - 只在目录被裁剪或打包失败时触发
    raise SystemExit(
        f"cannot import bugfix_agent: {e}\n"
        f"expected vendored copy under {_VENDOR}; "
        "re-copy it or set AGENT1_USE_INSTALLED=1 with an installed bugfix-agent"
    ) from e


def _load_defect_batch(value: Union[str, Path, dict[str, Any], DefectBatch]) -> DefectBatch:
    """加载并校验 defect-batch（路径 / dict / 模型）。与 workflow.run 的同名函数一致。"""
    if isinstance(value, DefectBatch):
        return value
    if isinstance(value, dict):
        return validate_defect_batch(value)
    data = json.loads(Path(value).read_text(encoding="utf-8"))
    return validate_defect_batch(data)


def _dump(out: str, model: DefectBatch) -> None:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def _cmd_prepare(args: argparse.Namespace) -> int:
    batch = run_defect_batch_prepare(
        product_line=args.product_line,
        source=args.source,
        posture=args.posture,
    )
    _dump(args.out, batch)
    print(
        json.dumps(
            {"ok": True, "tickets": len(batch.tickets), "funnel": batch.funnel, "out": args.out},
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_apply_review(args: argparse.Namespace) -> int:
    batch = _load_defect_batch(args.batch)
    payload = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
    review_file = IntentReviewFile.model_validate(payload)
    updated = apply_intent_review(batch, review_file.adjustments)
    _dump(args.out, updated)
    print(
        json.dumps(
            {
                "ok": True,
                "tickets": len(updated.tickets),
                "funnel": updated.funnel,
                "adjustments": len(review_file.adjustments),
                "out": args.out,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_self_check(_: argparse.Namespace) -> int:
    """校验 _vendor 副本与 VENDOR.json 记录的哈希一致（防漂移）。"""
    manifest_path = _manifest_path()
    if not manifest_path.exists():
        print(f"no manifest at {manifest_path}", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"vendor files : {len(manifest['files'])}")
    print(f"source       : {manifest['source']}")
    print(f"commit       : {manifest['commit']}")
    print(f"copiedAt     : {manifest['copiedAt']}")

    if _FROZEN:
        # onefile 打包后源码在归档里，运行时无法逐文件比哈希。
        print("mode         : frozen single-file build (hashes not verifiable at runtime)")
        return 0

    bad, missing = [], []
    for rel, want in manifest["files"].items():
        p = _VENDOR / rel
        if not p.exists():
            missing.append(rel)
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != want:
            bad.append(rel)
    print(f"vendor files : {len(manifest['files'])}")
    print(f"source       : {manifest['source']}")
    print(f"copiedAt     : {manifest['copiedAt']}")
    for rel in missing:
        print(f"  MISSING  {rel}")
    for rel in bad:
        print(f"  CHANGED  {rel}")
    if not missing and not bad:
        print("  OK  all hashes match")
        return 0
    return 1


_PASSTHROUGH = {"preflight": (_preflight, "preflight"), "xlsx-to-raw": (_xlsx, "xlsx-to-raw")}


def _run_passthrough(name: str, rest: list[str]) -> int:
    """把剩余参数原样交给同目录脚本的 main()，避免再抄一份 argparse 定义。"""
    module, prog = _PASSTHROUGH[name]
    if module is None:
        raise SystemExit(f"{prog} not available in this build")
    saved = sys.argv
    sys.argv = [prog, *rest]
    try:
        module.main()
    finally:
        sys.argv = saved
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # 这两个子命令的参数是底下脚本自己的，不能先给外层 argparse 吃一遍
    # （ REMAINDER 遇上 `--source` 会被当成外层选项）。
    if raw and raw[0] in _PASSTHROUGH:
        return _run_passthrough(raw[0], raw[1:])
    parser = argparse.ArgumentParser(
        prog="agent1",
        description="Agent-1 standalone: defect-batch prepare / review (no LangGraph)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser("prepare-batch", help="ingest → defect-batch.json")
    prep.add_argument("--product-line", required=True)
    prep.add_argument("--source", required=True, help="JSON or platform CSV")
    prep.add_argument("--posture", choices=["alpha", "beta"], default="beta")
    prep.add_argument("--out", required=True, help="Write defect-batch JSON")
    prep.set_defaults(func=_cmd_prepare)

    review = sub.add_parser("apply-review", help="Apply intent-review overrides")
    review.add_argument("--batch", required=True, help="Existing defect-batch JSON")
    review.add_argument("--overrides", required=True, help="JSON {adjustments: [...]}")
    review.add_argument("--out", required=True, help="Write updated defect-batch JSON")
    review.set_defaults(func=_cmd_apply_review)

    chk = sub.add_parser("self-check", help="Verify vendored copy against VENDOR.json")
    chk.set_defaults(func=_cmd_self_check)

    pre = sub.add_parser("preflight", help="Column-mapping health check (Step 0); args go to preflight.py")
    pre.set_defaults(func=_cmd_self_check)

    xl = sub.add_parser("xlsx-to-raw", help="Convert .xlsx to raw-defects.json; args go to xlsx_to_raw_defects.py")
    xl.set_defaults(func=_cmd_self_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
