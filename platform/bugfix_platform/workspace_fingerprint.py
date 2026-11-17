"""Read-only workspace fingerprints shared by investigation and repair."""
import hashlib
import os
from pathlib import Path
from typing import Iterable

_SKIP_COPY = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".bugfix",
    ".bugfix-runs",
    ".codegraph",
}

_SKIP_FILES = frozenset({".env", "credentials.json"})


def _list_source_files(root: Path) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_COPY]
        for name in filenames:
            if name in _SKIP_FILES:
                continue
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            out.append(rel)
    return out


def workspace_digest(root: Path) -> str:
    """所有普通源文件的内容摘要，不只 dirty / 首个文件。"""
    return _content_digest(root, _list_source_files(root))


def _content_digest(root: Path, rels: Iterable[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(rels):
        path = root / rel
        h.update(rel.encode("utf-8"))
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()[:16]
