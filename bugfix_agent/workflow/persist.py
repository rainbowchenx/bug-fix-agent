from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def persist_artifact(artifact_dir: Optional[str], filename: str, data: dict[str, Any]) -> Optional[Path]:
    """Best-effort write of one artifact JSON under `artifact_dir`.

    Returns the written path, or None when persistence is disabled / fails.
    Failures never raise — durable orchestration must not abort on disk IO.
    """
    if not artifact_dir:
        return None
    try:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError:
        return None
