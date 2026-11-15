"""逐票 attempt 落盘：先写文件再提交；已有锁则 busy。"""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_contracts.repair import AttemptRecord

_LOCK_NAME = ".write.lock"


class AttemptStoreBusy(RuntimeError):
    """同一产物目录已有写入者。"""


def save_attempt(root: Path, attempt: AttemptRecord) -> Path:
    """原子写入 ``defects/<id>/attempts/<attemptId>/attempt.json``。"""
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    lock = base / _LOCK_NAME
    if lock.is_file():
        raise AttemptStoreBusy("artifact root is busy")
    lock.write_text("1", encoding="utf-8")
    try:
        dest = (
            base
            / "defects"
            / attempt.defectId
            / "attempts"
            / attempt.attemptId
            / "attempt.json"
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(attempt.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(dest)
        latest = base / "defects" / attempt.defectId / "latest.json"
        latest.write_text(
            json.dumps({"attemptId": attempt.attemptId, "path": str(dest)}, ensure_ascii=False),
            encoding="utf-8",
        )
        return dest
    finally:
        if lock.is_file():
            lock.unlink()


def load_attempt(path: Path) -> AttemptRecord:
    return AttemptRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
