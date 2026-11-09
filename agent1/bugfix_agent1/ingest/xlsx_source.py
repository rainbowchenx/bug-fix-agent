"""把 Excel 导出转成 ``RawDefect``，供 ``preloaded``  ingest 使用。

与 :mod:`bugfix_agent1.ingest.csv_source` 对称：CSV 走 ``csv.DictReader``，
这里走 openpyxl；两者之后共用 :func:`field_map.row_to_raw_dict` 的别名映射，
所以中文表头 / 英文表头的行为完全一致。

``main()`` 也放在这里，而不是放在 ``scripts/`` —— 因为同一个子命令有两个
消费者（``bugfix_agent1/scripts/xlsx_to_raw_defects.py`` 和 Agent-1 的
``agent1 xlsx-to-raw``），把 argparse 定义放两份就会多一处漂移点。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bugfix_contracts.defect_batch import RawDefect
from bugfix_agent1.ingest.field_map import FIELD_ALIASES, row_to_raw_dict


def _require_openpyxl() -> Any:
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover - openpyxl 是硬依赖
        raise SystemExit("openpyxl is required: pip install openpyxl") from e
    return openpyxl


def _cell(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def xlsx_headers(path: str | Path, sheet: str | None = None) -> list[str]:
    """返回工作簿第一行的表头（含空列）。"""
    openpyxl = _require_openpyxl()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        return [_cell(c.value) for c in next(ws.iter_rows(min_row=1, max_row=1))]
    finally:
        wb.close()


def load_xlsx_defects(
    path: str | Path,
    *,
    sheet: str | None = None,
    limit: int | None = None,
) -> list[RawDefect]:
    """读取 Excel 导出，返回映射成功的 ``RawDefect`` 列表。

    Args:
        path: ``.xlsx`` 路径。
        sheet: 工作表名；``None`` 取第一个。
        limit: 最多返回多少条（用于抽样）。

    Raises:
        ValueError: 非空表但一行都没映射出来（列名对不上时最常发生）。
    """
    openpyxl = _require_openpyxl()
    p = Path(path)
    wb = openpyxl.load_workbook(p, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
        headers = [_cell(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]

        defects: list[RawDefect] = []
        seen_rows = 0
        for r in range(2, ws.max_row + 1):
            row_map = {
                h: ws.cell(r, i + 1).value
                for i, h in enumerate(headers)
                if h
            }
            if not any(_cell(v) for v in row_map.values()):
                # 导出尾部常带成片空行，max_row 会把它们算进来。
                continue
            seen_rows += 1
            mapped = row_to_raw_dict(row_map)
            if not mapped:
                continue
            defects.append(RawDefect.model_validate(mapped))
            if limit is not None and len(defects) >= limit:
                break
    finally:
        wb.close()

    # 静默 0 行的老毛病：非空表但一条也没转出来，会和「全被筛掉」混淆。
    if seen_rows and not defects:
        raise ValueError(
            f"mapped 0 of {seen_rows} rows from {p.name}: no row had both an id "
            f"and a title. Headers={headers}. Need a column matching "
            f"{FIELD_ALIASES['defectId']} / {FIELD_ALIASES['title']}."
        )
    return defects


def main(argv: list[str] | None = None) -> None:
    """共享 CLI：写 ``raw-defects.json``，供 ``preloaded`` ingest 消费。"""
    ap = argparse.ArgumentParser(
        prog="xlsx-to-raw",
        description="Convert a defect Excel export into raw-defects JSON.",
    )
    ap.add_argument("--xlsx", required=True, type=Path)
    ap.add_argument("--product-line", required=True)
    ap.add_argument("--sheet", default=None, help="Worksheet name (default: first sheet)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    defects = load_xlsx_defects(args.xlsx, sheet=args.sheet, limit=args.limit)
    payload = {
        "schemaVersion": "0.1.0",
        "productLine": args.product_line,
        "defects": [d.model_dump(exclude_none=True) for d in defects],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(defects)} defects → {args.out}", file=sys.stderr)
