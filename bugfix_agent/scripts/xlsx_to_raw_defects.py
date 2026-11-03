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


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise SystemExit("openpyxl is required: pip install openpyxl") from e


ALIASES = {
    # Prefer Chinese Excel headers; also accept English CSV export aliases
    # (see csv_to_raw_defects.py — platform typo "describle" is intentional).
    "defectId": ["缺陷ID", "defectId", "ID", "id"],
    "title": ["缺陷标题", "defectTitle", "标题", "title"],
    "description": ["缺陷描述", "describle", "描述", "description"],
    "status": ["缺陷状态", "defectStatus", "状态", "status"],
    "flowStatus": ["流程状态", "flowStatusName", "flowStatus"],
    "testModule": ["测试模块", "testModule"],
    "fieldType": ["类型", "缺陷类型", "fieldType", "type"],
    "severity": ["严重级别", "severityName", "severity"],
    "createdAt": ["创建时间", "createDate", "createdAt"],
    "duplicateOf": ["关联重复缺陷编号", "关联缺陷ID", "duplicateOf"],
}


def pick(header_index: dict[str, int], names: list[str]) -> int | None:
    for n in names:
        if n in header_index:
            return header_index[n]
    return None


def cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def convert(xlsx: Path, product_line: str, sheet: str | None, limit: int | None) -> dict:
    _require_openpyxl()
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    headers = [cell_str(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    header_index = {h: i for i, h in enumerate(headers) if h}
    cols = {k: pick(header_index, v) for k, v in ALIASES.items()}
    if cols["defectId"] is None or cols["title"] is None:
        raise SystemExit(f"missing required columns defectId/title in {xlsx}; headers={headers[:20]}")

    defects: list[dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        defect_id = cell_str(ws.cell(r, cols["defectId"] + 1).value)
        title = cell_str(ws.cell(r, cols["title"] + 1).value)
        if not defect_id or not title:
            continue
        row: dict[str, Any] = {
            "defectId": defect_id,
            "title": title,
            "description": cell_str(ws.cell(r, cols["description"] + 1).value) if cols["description"] is not None else "",
        }
        for key in ("status", "flowStatus", "testModule", "fieldType", "severity", "createdAt", "duplicateOf"):
            idx = cols[key]
            if idx is None:
                continue
            val = cell_str(ws.cell(r, idx + 1).value)
            if val:
                row[key] = val
        defects.append(row)
        if limit is not None and len(defects) >= limit:
            break
    wb.close()
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
