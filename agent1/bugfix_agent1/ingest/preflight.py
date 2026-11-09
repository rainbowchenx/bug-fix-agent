#!/usr/bin/env python3
"""Preflight an export: what will the funnel actually see?

The rule funnel returns ``{"ok": true, "tickets": 0}`` when it cannot map a
single row -- ``ok`` means "the rules ran", not "the data was read". This
script is the missing signal: it prints the source row count, which column
fed each contract field, and which columns were left over.

Usage:
    python preflight.py --source path/to/export.csv
    python preflight.py --source export.xlsx --sheet Sheet1
    python preflight.py --source export.csv --batch defect-batch.json   # 再比对产物
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

# 单一真源：别名表与空模板判定都直接 import，不在这里另抄一份。
from bugfix_agent1.defect_batch.distill import is_empty_template, split_description
from bugfix_agent1.ingest.field_map import FIELD_ALIASES, METADATA_KEYS


def _cell(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _pick(row: dict[str, Any], aliases: list[str]) -> tuple[str, str]:
    """返回 (命中的列名, 值)。大小写兜底与 field_map.pick_field 保持一致。"""
    for name in aliases:
        if name in row:
            val = _cell(row.get(name))
            if val:
                return name, val
    lower = {str(k).lower(): k for k in row}
    for name in aliases:
        key = lower.get(name.lower())
        if key is not None:
            val = _cell(row.get(key))
            if val:
                return key, val
    return "", ""


def _iter_csv(path: Path, encoding: str) -> Iterator[dict[str, Any]]:
    with path.open(encoding=encoding, newline="") as fh:
        yield from csv.DictReader(fh)


def _iter_xlsx(path: Path, sheet: str | None) -> Iterator[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as err:
        raise SystemExit("openpyxl is required for .xlsx: pip install openpyxl") from err
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    headers = [_cell(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    for r in range(2, ws.max_row + 1):
        yield {
            h: ws.cell(r, i + 1).value
            for i, h in enumerate(headers)
            if h
        }
    wb.close()


def _iter_json(path: Path) -> Iterator[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("defects") if isinstance(data, dict) else data
    if isinstance(rows, list):
        yield from (r for r in rows if isinstance(r, dict))


def load_rows(source: Path, sheet: str | None, encoding: str) -> list[dict[str, Any]]:
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return list(_iter_csv(source, encoding))
    if suffix in (".xlsx", ".xlsm"):
        return list(_iter_xlsx(source, sheet))
    if suffix == ".json":
        return list(_iter_json(source))
    raise SystemExit(f"unsupported source type: {source.suffix}")


def main() -> None:
    try:  # Windows 控制台默认 cp936，中文列名会乱码
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--sheet", default=None, help="xlsx worksheet (default: first)")
    ap.add_argument("--encoding", default="utf-8-sig")
    ap.add_argument("--batch", type=Path, default=None, help="比对已产出的 defect-batch.json")
    ap.add_argument("--show", type=int, default=3, help="样例值打印条数")
    args = ap.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"source not found: {args.source}")

    rows = load_rows(args.source, args.sheet, args.encoding)
    headers = list(rows[0].keys()) if rows else []

    print(f"source      : {args.source.name}")
    print(f"rows        : {len(rows)}")
    print(f"columns     : {len(headers)}")
    print()

    hit_cols: dict[str, str] = {}
    print("-- contract fields --")
    for canonical, aliases in FIELD_ALIASES.items():
        col, val = _pick(rows[0], aliases) if rows else ("", "")
        hit_cols[canonical] = col
        mark = "OK  " if col else "MISS"
        shown = val.replace("\n", " ")[:48]
        print(f"  [{mark}] {canonical:12s} <- {col or '(none)':14s} {shown!r}")
    print()

    claimed = {c for c in hit_cols.values() if c}
    claimed |= {k for k in METADATA_KEYS if k in headers}
    unused = [h for h in headers if h not in claimed]
    if unused:
        print(f"-- unplaced columns ({len(unused)}) --")
        for h in unused:
            sample = _cell(rows[0].get(h)).replace("\n", " ")[:40] if rows else ""
            print(f"  {h}: {sample!r}")
        print()

    # 内容体检
    mapped = 0
    desc_present = 0
    empty_template = 0
    module_present = 0
    for r in rows:
        _, did = _pick(r, FIELD_ALIASES["defectId"])
        _, title = _pick(r, FIELD_ALIASES["title"])
        if did and title:
            mapped += 1
        _, desc = _pick(r, FIELD_ALIASES["description"])
        if desc:
            desc_present += 1
            obs, exp, stp = split_description(desc)
            if is_empty_template(desc, obs, exp, stp):
                empty_template += 1
        if _pick(r, FIELD_ALIASES["testModule"])[1]:
            module_present += 1

    print("-- content --")
    print(f"  rows mappable (id+title) : {mapped}/{len(rows)}")
    print(f"  description present      : {desc_present}/{len(rows)}")
    print(f"  description is an unfilled template : {empty_template}/{len(rows)}")
    print(f"  testModule present       : {module_present}/{len(rows)}")
    print()

    # 判定
    verdicts: list[str] = []
    if mapped == 0:
        verdicts.append(
            "BLOCKER: 0 rows map to the contract. prepare-batch will report "
            '{"ok": true, "tickets": 0}. Fix the column aliases first.'
        )
    elif mapped < len(rows):
        verdicts.append(f"WARN: {len(rows) - mapped} row(s) lack an ID or title and will be dropped.")
    if desc_present == 0:
        verdicts.append("WARN: no description at all — intent review has nothing to read.")
    elif empty_template == len(rows):
        verdicts.append(
            "WARN: every description is the platform's unfilled template. "
            "Do not invent intents; report that the export carries no content."
        )
    if module_present == 0:
        verdicts.append(
            "WARN: no module column mapped — every cluster collapses into _unmoduled, "
            "so the L1 grouping dimension is dead for this export."
        )

    if args.batch is not None:
        try:
            batch = json.loads(args.batch.read_text(encoding="utf-8"))
            n = len(batch.get("tickets") or [])
            print(f"-- batch comparison --\n  batch tickets: {n} / source rows: {len(rows)}")
            if n != len(rows):
                verdicts.append(
                    f"MISMATCH: batch has {n} tickets but the source has {len(rows)} rows — "
                    "do not report this funnel as if it covered the export."
                )
            else:
                print("  counts agree")
            print()
        except Exception as err:  # noqa: BLE001
            print(f"  could not read batch: {err}\n")

    if verdicts:
        print("-- verdict --")
        for v in verdicts:
            print(f"  * {v}")
    else:
        print("-- verdict --\n  looks healthy: rows map, description present, module present")

    print()
    dist = Counter(_pick(r, FIELD_ALIASES["testModule"])[1] or "<empty>" for r in rows)
    top = dist.most_common(8)
    print("-- module distribution (top 8) --")
    for name, cnt in top:
        print(f"  {cnt:4d}  {name}")


if __name__ == "__main__":
    main()
