from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from bugfix_agent.contracts.defect_batch import RawDefect
from bugfix_agent.ingest.field_map import row_to_raw_dict


def load_platform_csv(
    path: str | Path,
    *,
    limit: Optional[int] = None,
    encoding: str = "utf-8-sig",
) -> list[RawDefect]:
    """读取缺陷平台导出 CSV，映射为 ``RawDefect`` 列表。

    列名经 ``row_to_raw_dict``（含平台拼写 ``describle``）。缺 ID 或标题的
    行会被跳过。

    Args:
        path: CSV 路径。
        limit: 最多保留多少条有效缺陷；默认不限制。
        encoding: 文件编码，默认 ``utf-8-sig`` 以吃掉 BOM。

    Returns:
        映射成功的 ``RawDefect`` 列表。

    Raises:
        ValueError: CSV 没有表头，或表头有行可读但一行都映射不出来。
    """
    p = Path(path)
    defects: list[RawDefect] = []
    seen_rows = 0
    with p.open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {p}")
        for row in reader:
            seen_rows += 1
            mapped = row_to_raw_dict(row)
            if not mapped:
                continue
            defects.append(RawDefect.model_validate(mapped))
            if limit is not None and len(defects) >= limit:
                break

    # A fully unmappable export used to surface as `{"ok": true,
    # "tickets": 0}` -- indistinguishable from "every ticket was screened
    # out". Column names are the usual culprit, so say so and name them.
    if seen_rows and not defects:
        headers = csv_headers(p, encoding=encoding)
        raise ValueError(
            f"mapped 0 of {seen_rows} rows from {p.name}: no column matched "
            f"defectId or title. Headers={headers}. "
            f"Add the missing spelling to FIELD_ALIASES in ingest/field_map.py."
        )
    return defects


def csv_headers(path: str | Path, encoding: str = "utf-8-sig") -> list[str]:
    with Path(path).open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or [])
