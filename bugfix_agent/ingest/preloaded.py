from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from bugfix_agent.contracts.defect_batch import RawDefect, RawDefectsFile
from bugfix_agent.ingest.csv_source import load_platform_csv


Source = Union[str, Path, dict[str, Any], list[Any]]


def load_preloaded(source: Source) -> list[RawDefect]:
    """Load raw defects from JSON list/object, raw-defects file, or platform CSV."""
    if isinstance(source, list):
        return [_coerce_item(x) for x in source]
    if isinstance(source, dict):
        # Already-normalized file OR a single platform row
        if "defects" in source:
            parsed = RawDefectsFile.model_validate(source)
            return parsed.defects
        mapped = _coerce_item(source)
        return [mapped]

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_platform_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [_coerce_item(x) for x in data]
    if isinstance(data, dict) and "defects" in data:
        return RawDefectsFile.model_validate(data).defects
    return [_coerce_item(data)]


def _coerce_item(item: Any) -> RawDefect:
    """Accept either canonical RawDefect keys or platform row keys."""
    if isinstance(item, RawDefect):
        return item
    if not isinstance(item, dict):
        raise TypeError(f"defect item must be dict, got {type(item)}")
    # Fast path: already canonical
    if "title" in item and "defectId" in item:
        return RawDefect.model_validate(item)
    from bugfix_agent.ingest.field_map import row_to_raw_dict

    mapped = row_to_raw_dict(item)
    if not mapped:
        # fall through to pydantic for a clear error
        return RawDefect.model_validate(item)
    return RawDefect.model_validate(mapped)
