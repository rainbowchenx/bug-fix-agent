"""Agent-2 实仓评测：跑真仓 + 算 hit@1 / hit@k / 候选噪声。

自动评测（`tests/platform/test_cartography_eval.py`）只能跑人造夹具；真实仓的
规模、命名、语义都不在夹具里。这个脚本补的就是那一层。

真值来源必须是**能从仓里复核**的东西（人工标注当然最准，但成本高）；本脚本
只负责算分，不负责编答案。

用法::

    python packaging/eval_agent2.py \\
        --repo /path/to/repo --profile device_web \\
        --batch /path/to/defect-batch.json \\
        --cases <eval-dir>/cases.json \\
        --mode sdk --max-turns 60 \\
        --out <eval-dir>/sdk.json

评测数据不入库：``cases.json`` 与跑批产物在各业务侧 ``bug-fix-测试专用/agent2开发评测/``
（transport 2026-11-10 实场评测、2026-11-12 三仓基线）。仓里只留可复跑的脚本与测试。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in ("platform", "contracts"):
    candidate = ROOT / extra
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bugfix_contracts.defect_batch import DefectBatch, load_defect_batch  # noqa: E402
from bugfix_contracts.env import load_env_file  # noqa: E402
from bugfix_platform.agents.cartographer import run_cartographer  # noqa: E402


def _rel(candidate) -> str:
    rel = str(candidate.path).replace("\\", "/")
    repo_path = getattr(candidate, "repoPath", ".") or "."
    if repo_path not in (".", "", None):
        rel = f"{repo_path.rstrip('/')}/{rel.lstrip('/')}"
    return rel


def _hit(match, prefix: str, k: int) -> bool:
    prefix = prefix.replace("\\", "/").rstrip("/")
    for cand in match.candidates[:k]:
        rel = _rel(cand)
        if rel == prefix or rel.startswith(prefix + "/") or rel == prefix:
            return True
        if prefix.endswith("/") and rel.startswith(prefix):
            return True
    return False


def _subset(batch: DefectBatch, ids: set[str]) -> DefectBatch:
    tickets = [t for t in batch.tickets if t.defectId in ids]
    data = batch.model_dump()
    data["tickets"] = [t.model_dump() for t in tickets]
    strict = sum(1 for t in tickets if t.pool == "strict")
    funnel = dict(data.get("funnel") or {})
    funnel.update({"total": len(tickets), "strict": strict})
    data["funnel"] = funnel
    # 只保留与子集相关的簇，避免 clusterId 指向不存在的票
    cluster_ids = {t.clusterId for t in tickets if t.clusterId}
    data["clusters"] = [c for c in data.get("clusters") or [] if c.get("id") in cluster_ids]
    return DefectBatch.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent-2 实仓评测")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--profile", required=True,
                    choices=["electron_node", "micro_frontend", "device_web", "unknown"])
    ap.add_argument("--batch", required=True, help="defect-batch.json（Agent-1 产物）")
    ap.add_argument("--cases", required=True, help="真值 json：cases[].defectId / expectPathPrefix")
    ap.add_argument("--mode", default="heuristic", choices=["heuristic", "sdk"])
    ap.add_argument("--max-turns", type=int, default=None,
                    help="SDK 轮数上限（写进 BUGFIX_CARTOGRAPHY_MAX_TURNS）")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只跑这些 defectId（分批喂 SDK 用）")
    ap.add_argument("--out", default=None, help="把 code-knowledge 写到这里")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    load_env_file()
    if args.max_turns is not None:
        os.environ["BUGFIX_CARTOGRAPHY_MAX_TURNS"] = str(args.max_turns)

    repo = Path(args.repo)
    batch = load_defect_batch(Path(args.batch))
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    case_ids = [c["defectId"] for c in cases]
    wanted = set(args.only) if args.only else set(case_ids)
    batch = _subset(batch, wanted)

    started = time.time()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        knowledge = run_cartographer(
            work_dir=repo,
            defect_batch=batch,
            cartography_mode=args.mode,
            cartography_profile=args.profile,
        )
    elapsed = time.time() - started
    diagnostics = [ln for ln in err.getvalue().splitlines() if ln.startswith("[agent2]")]

    by_id = {m.defectId: m for m in knowledge.defectCodeMatches}
    rows = []
    for case in cases:
        if case["defectId"] not in wanted:
            continue
        match = by_id.get(case["defectId"])
        prefix = case["expectPathPrefix"]
        cands = [_rel(c) for c in (match.candidates if match else [])]
        rows.append({
            "id": case.get("id", case["defectId"]),
            "defectId": case["defectId"],
            "expect": prefix,
            "hit1": bool(match and _hit(match, prefix, 1)),
            "hit3": bool(match and _hit(match, prefix, 3)),
            "confidence": match.confidence if match else None,
            "nCandidates": len(cands),
            "top1": cands[0] if cands else None,
            "candidates": cands[:3],
        })

    hit1 = sum(r["hit1"] for r in rows)
    hit3 = sum(r["hit3"] for r in rows)
    enrich = [h for h in knowledge.secondaryHints if h.startswith("enrich=")]

    if not args.quiet:
        print(f"  mode={args.mode}  profile={args.profile}  票={len(batch.tickets)}  "
              f"耗时={elapsed:.1f}s  modules={len(knowledge.architecture.modules)}")
        for line in diagnostics:
            print(f"  {line}")
        print(f"  {'用例':24s} {'@1':3s} {'@3':3s} {'n':>2s}  期望 → top1")
        for r in rows:
            print(f"  {r['id']:24s} {'OK' if r['hit1'] else '--':3s} "
                  f"{'OK' if r['hit3'] else '--':3s} {r['nCandidates']:2d}  "
                  f"{r['expect']}\n  {'':24s} {'':3s} {'':3s} {'':2s}  → {r['top1']}")
        print(f"\n  hit@1 = {hit1}/{len(rows)}   hit@3 = {hit3}/{len(rows)}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "mode": args.mode,
            "profile": args.profile,
            "repo": str(repo),
            "elapsedSeconds": round(elapsed, 1),
            "maxTurns": os.environ.get("BUGFIX_CARTOGRAPHY_MAX_TURNS"),
            "enrich": enrich,
            "diagnostics": diagnostics,
            "hitAt1": f"{hit1}/{len(rows)}",
            "hitAt3": f"{hit3}/{len(rows)}",
            "rows": rows,
            "knowledge": knowledge.model_dump(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> {out}")

    return 0 if hit3 == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
