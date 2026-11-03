#!/usr/bin/env python3
"""Convert a desensitized defect CSV export into raw-defects JSON for Agent-1.

Supports the English camelCase headers used by `缺陷拉取/脱敏/*.csv`
(e.g. defectTitle / describle / defectStatus), plus Chinese Excel aliases.

Usage:
  python3 bugfix_agent/scripts/csv_to_raw_defects.py \\
    --csv 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \\
    --product-line ax-hybrid \\
    --out 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.raw-defects.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

# Maps RawDefect fields → possible CSV/Excel column names (first hit wins).
ALIASES: dict[str, list[str]] = {
    "defectId": ["defectId", "缺陷ID", "ID", "id"],
    "title": ["defectTitle", "缺陷标题", "标题", "title"],
    # Platform typo "describle" is intentional and must stay.
    "description": ["describle", "description", "缺陷描述", "描述"],
    "status": ["defectStatus", "缺陷状态", "状态", "status"],
    "flowStatus": ["flowStatusName", "flowStatus", "流程状态"],
    "testModule": ["testModule", "测试模块"],
    "fieldType": ["fieldType", "类型", "缺陷类型", "type"],
    "severity": ["severityName", "severity", "严重级别"],
    "createdAt": ["createDate", "createdAt", "创建时间"],
    "duplicateOf": [
        "duplicateOf",
        "关联重复缺陷编号",
        "关联缺陷ID",
        "relationDefectId",
    ],
}

# Optional metadata-only columns (never used as screen/cluster keys).
META_ALIASES: dict[str, list[str]] = {
    "projectId": ["testRequestId", "所属项目编号", "projectId"],
    "softName": ["softName", "产品名称", "productName"],
    "revision": ["revision", "产品版本", "productVersion"],
    "detectingActivity": ["detectingActivityI18n", "检出活动"],
}


def _pick(header_index: dict[str, int], names: list[str]) -> int | None:
    for n in names:
        if n in header_index:
            return header_index[n]
    return None


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _infer_project_id(csv_path: Path, rows_meta: list[dict[str, str]]) -> str | None:
    m = re.match(r"^(PJ\d+[A-Z0-9]+)", csv_path.name, re.I)
    if m:
        return m.group(1)
    for meta in rows_meta:
        pid = (meta.get("projectId") or "").strip()
        if pid:
            # strip trailing batch suffix like G01 if present later; keep raw for now
            return re.sub(r"G\d+$", "", pid) or pid
    return None


def convert(csv_path: Path, product_line: str, limit: int | None) -> dict[str, Any]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration as e:
            raise SystemExit(f"empty csv: {csv_path}") from e
        header_index = {h.strip(): i for i, h in enumerate(headers) if h and h.strip()}
        cols = {k: _pick(header_index, v) for k, v in ALIASES.items()}
        meta_cols = {k: _pick(header_index, v) for k, v in META_ALIASES.items()}
        if cols["defectId"] is None or cols["title"] is None:
            raise SystemExit(
                f"missing required columns defectId/title in {csv_path}; "
                f"headers={list(header_index)[:25]}"
            )

        defects: list[dict[str, Any]] = []
        for row in reader:
            defect_id = _cell(row, cols["defectId"])
            title = _cell(row, cols["title"])
            if not defect_id or not title:
                continue
            item: dict[str, Any] = {
                "defectId": defect_id,
                "title": title,
                "description": _cell(row, cols["description"]),
            }
            for key in (
                "status",
                "flowStatus",
                "testModule",
                "fieldType",
                "severity",
                "createdAt",
                "duplicateOf",
            ):
                val = _cell(row, cols[key])
                if val:
                    item[key] = val

            meta: dict[str, Any] = {}
            for key, idx in meta_cols.items():
                val = _cell(row, idx)
                if val:
                    meta[key] = val
            if meta:
                item["metadata"] = meta

            defects.append(item)
            if limit is not None and len(defects) >= limit:
                break

    if not product_line:
        raise SystemExit("--product-line is required")

    return {
        "schemaVersion": "0.1.0",
        "productLine": product_line,
        "defects": defects,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument(
        "--product-line",
        required=True,
        help="Agent-1 productLine label (e.g. ax-hybrid / project id)",
    )
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    if not args.csv.is_file():
        raise SystemExit(f"csv not found: {args.csv}")
    payload = convert(args.csv, args.product_line, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(payload['defects'])} defects → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
