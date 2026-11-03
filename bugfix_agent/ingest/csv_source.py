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
    """Load a 缺陷拉取-style CSV into RawDefect list."""
    p = Path(path)
    defects: list[RawDefect] = []
    with p.open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {p}")
        for row in reader:
            mapped = row_to_raw_dict(row)
            if not mapped:
                continue
            defects.append(RawDefect.model_validate(mapped))
            if limit is not None and len(defects) >= limit:
                break
    return defects


def csv_headers(path: str | Path, encoding: str = "utf-8-sig") -> list[str]:
    with Path(path).open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or [])
