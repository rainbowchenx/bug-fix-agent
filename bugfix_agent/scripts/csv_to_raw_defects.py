#!/usr/bin/env python3
"""Convert platform 缺陷拉取 CSV into raw-defects JSON.

Usage:
  python3 csv_to_raw_defects.py --csv path.csv --product-line hc --out raw.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bugfix_agent.ingest.csv_source import load_platform_csv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--product-line", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    defects = load_platform_csv(args.csv, limit=args.limit)
    payload = {
        "schemaVersion": "0.1.0",
        "productLine": args.product_line,
        "defects": [d.model_dump(exclude_none=True) for d in defects],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(defects)} defects → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
