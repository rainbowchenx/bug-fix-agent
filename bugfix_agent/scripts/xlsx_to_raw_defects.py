#!/usr/bin/env python3
"""Convert a defect Excel export into raw-defects JSON for Agent-1 preloaded ingest.

Usage:
  python3 xlsx_to_raw_defects.py --xlsx path.xlsx --product-line hc --out raw.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running as a script from repo root / scripts dir.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bugfix_agent.ingest.field_map import FIELD_ALIASES, row_to_raw_dict  # noqa: E402


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise SystemExit("openpyxl is required: pip install openpyxl") from e


def convert(xlsx: Path, product_line: str, sheet: str | None, limit: int | None) -> dict:
    _require_openpyxl()
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    headers = [
        ("" if ws.cell(1, c).value is None else str(ws.cell(1, c).value).strip())
        for c in range(1, ws.max_column + 1)
    ]
    defects: list[dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        row_map: dict[str, Any] = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            val = ws.cell(r, i + 1).value
            row_map[h] = "" if val is None else str(val).strip()
        mapped = row_to_raw_dict(row_map)
        if not mapped:
            continue
        defects.append(mapped)
        if limit is not None and len(defects) >= limit:
            break
    wb.close()
    if not defects:
        # help diagnose alias misses
        raise SystemExit(
            f"no defects mapped from {xlsx}; headers={headers[:20]}; "
            f"need aliases covering {list(FIELD_ALIASES['defectId'])} / {list(FIELD_ALIASES['title'])}"
        )
    return {
        "schemaVersion": "0.1.0",
        "productLine": product_line,
        "defects": defects,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", required=True, type=Path)
    ap.add_argument("--product-line", required=True)
    ap.add_argument("--sheet", default=None, help="Worksheet name (default: first sheet)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    payload = convert(args.xlsx, args.product_line, args.sheet, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(payload['defects'])} defects → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
