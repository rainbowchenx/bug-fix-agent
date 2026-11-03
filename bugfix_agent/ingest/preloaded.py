from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bugfix_agent.contracts.defect_batch import RawDefect, RawDefectsFile


def load_preloaded(source: str | Path | dict[str, Any] | list[Any]) -> list[RawDefect]:
    if isinstance(source, list):
        return [RawDefect.model_validate(x) for x in source]
    if isinstance(source, dict):
        parsed = RawDefectsFile.model_validate(source)
        return parsed.defects
    path = Path(source)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [RawDefect.model_validate(x) for x in data]
    parsed = RawDefectsFile.model_validate(data)
    return parsed.defects
