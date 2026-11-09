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
    "defectId": ["缺陷单号", "缺陷ID", "缺陷编号", "ID", "id"],
    "title": ["缺陷标题", "标题", "title"],
    "description": ["缺陷描述", "描述", "description"],
    "status": ["缺陷状态", "状态", "status"],
    "flowStatus": ["流程状态"],
    "testModule": ["测试模块", "所属模块"],
    "fieldType": ["类型", "缺陷类型", "type"],
    "severity": ["严重级别", "severity"],
    "createdAt": ["创建时间", "createdAt"],
    "duplicateOf": ["关联重复缺陷编号", "关联缺陷ID", "duplicateOf"],
}

# 与 bugfix_agent.ingest.field_map 保持单一真源：能 import 就用包的别名表。
# 两份表曾经漂过一次（都缺 `缺陷单号`），结果所有中文导出映射 0 行。
try:  # pragma: no cover - 取决于包是否可 import
    from bugfix_agent.ingest.field_map import FIELD_ALIASES as _PKG_ALIASES

    ALIASES = {k: list(v) for k, v in _PKG_ALIASES.items()}
except ImportError:
    pass


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
    seen_rows = 0
    for r in range(2, ws.max_row + 1):
        defect_id = cell_str(ws.cell(r, cols["defectId"] + 1).value)
        title = cell_str(ws.cell(r, cols["title"] + 1).value)
        if not defect_id and not title:
            continue
        seen_rows += 1
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

    # 静默 0 行的老毛病：非空表但一条也没转出来。宁可报错也别交空产物。
    if seen_rows and not defects:
        raise SystemExit(
            f"converted 0 of {seen_rows} rows from {xlsx.name}: no row had both an "
            f"id and a title. Headers={headers}. "
            "Check the ID/title column names against bugfix_agent/ingest/field_map.py."
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
