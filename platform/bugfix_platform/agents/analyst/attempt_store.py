"""逐票 attempt 落盘：目录锁覆盖整段写入；已有锁则 busy。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from bugfix_contracts.repair import AttemptRecord

_LOCK_NAME = ".write.lock"


class AttemptStoreBusy(RuntimeError):
    """同一产物目录已有写入者。"""


@contextmanager
def store_lock(root: Path) -> Iterator[Path]:
    """用 mkdir 占锁，避免先检查再写的窗口。"""
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    lock = base / _LOCK_NAME
    if lock.exists():
        raise AttemptStoreBusy("artifact root is busy")
    try:
        lock.mkdir()
    except FileExistsError as err:
        raise AttemptStoreBusy("artifact root is busy") from err
    try:
        yield base
    finally:
        if lock.is_dir():
            lock.rmdir()
        elif lock.is_file():
            lock.unlink()


def save_attempt(root: Path, attempt: AttemptRecord, *, already_locked: bool = False) -> Path:
    """原子写入 ``defects/<id>/attempts/<attemptId>/attempt.json``。"""

    def _write(base: Path) -> Path:
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

    if already_locked:
        return _write(Path(root))
    with store_lock(root) as base:
        return _write(base)


def load_attempt(path: Path) -> AttemptRecord:
    return AttemptRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
