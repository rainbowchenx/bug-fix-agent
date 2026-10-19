"""Export a slice of the official SWE-bench/SWE-bench_Lite test split."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Prefer mirror when huggingface.co is unreachable from this network.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from datasets import load_dataset


ADAPTER_KEYS = [
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "version",
    "environment_setup_commit",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--dataset",
        default="SWE-bench/SWE-bench_Lite",
        help="Official Lite dataset with image/eval_script fields",
    )
    args = parser.parse_args()

    ds = load_dataset(args.dataset, split="test")
    rows = ds.select(range(args.offset, min(args.offset + args.limit, len(ds))))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            obj = {k: row[k] for k in ADAPTER_KEYS if k in row}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} instances -> {out}")


if __name__ == "__main__":
    main()
