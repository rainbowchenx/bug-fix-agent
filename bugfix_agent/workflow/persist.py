"""validate_* 门禁的渐进产物落盘。

当设置了 ``ThreeAgentState.artifact_dir`` 时，每个门禁成功后立刻写出对应 JSON
（defect-batch → code-knowledge → analysis-report）。HTTP 借此在后续 Agent
仍在跑时，也能让 ``GET /v1/runs/:id`` 看到部分产物。

磁盘 IO 失败被吞掉：编排不能因写盘失败而中断；HTTP/CLI 收尾仍会按结果对象
再写一遍产物。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def persist_artifact(artifact_dir: Optional[str], filename: str, data: dict[str, Any]) -> Optional[Path]:
    """尽力把一份产物 JSON 写到 ``artifact_dir``。

    成功返回路径；未启用或失败返回 None。
    永不抛错——持久化编排不能因磁盘 IO 失败而中断。
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
