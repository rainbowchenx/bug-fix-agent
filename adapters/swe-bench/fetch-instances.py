#!/usr/bin/env python3
"""Fetch SWE-bench Lite instances into eval/swe/data (adapter-side only).

Tries HuggingFace `datasets` first; falls back to documenting network failure.
Usage:
  py -3.12 adapters/swe-bench/fetch-instances.py --out eval/swe/data/lite-full.jsonl --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "version",
    "environment_setup_commit",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    ap.add_argument("--split", default="test")
    args = ap.parse_args()

    # Common China mirror (optional)
    os.environ.setdefault("HF_ENDPOINT", os.environ.get("HF_ENDPOINT", "https://huggingface.co"))

    try:
        from datasets import load_dataset
    except ImportError:
        print("Install: py -3.12 -m pip install datasets", file=sys.stderr)
        return 2

    print(f"Loading {args.dataset} split={args.split} ...", flush=True)
    ds = load_dataset(args.dataset, split=args.split)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for row in ds:
            if n >= args.limit:
                break
            payload = {k: row.get(k) for k in FIELDS}
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            n += 1
    print(f"Wrote {n} instances -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
