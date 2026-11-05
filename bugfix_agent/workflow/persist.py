"""Progressive artifact persistence for validate_* gates.

When ``ThreeAgentState.artifact_dir`` is set, each successful gate writes its
JSON immediately (defect-batch → code-knowledge → analysis-report). HTTP uses
this so ``GET /v1/runs/:id`` can show partial outputs while later agents run.

IO failures are swallowed: orchestration must not die because a disk write
failed; the final HTTP/CLI path still rewrites artifacts from the result object.
"""

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
