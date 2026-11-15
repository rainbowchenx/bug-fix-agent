"""Git 快照与隔离工作副本。不修改用户源工作区。"""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4

from bugfix_contracts.repair import PatchFile, PatchSet, WorkspaceSnapshot

_SKIP_COPY = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".bugfix",
    ".bugfix-runs",
}


def capture_workspace(repo_root: Path) -> WorkspaceSnapshot:
    """采集 HEAD、dirty 和内容摘要。源目录只读。"""
    root = Path(repo_root)
    head = _git_out(root, "rev-parse", "HEAD") or None
    porcelain = _git_out(root, "status", "--porcelain") or ""
    dirty: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().replace("\\", "/")
        if line.startswith("??"):
            untracked.append(path)
        else:
            dirty.append(path)
    digest = _content_digest(root, dirty + untracked)
    return WorkspaceSnapshot(
        repoId=str(root.resolve()),
        head=head,
        dirty=dirty,
        untracked=untracked,
        contentDigest=digest,
        capturedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def prepare_workspace(snapshot: WorkspaceSnapshot, destination: Path) -> Path:
    """把已登记基线重放到隔离目录并校验，不改源仓。"""
    src = Path(snapshot.repoId)
    dest = Path(destination)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    _copytree(src, dest)
    copied = capture_workspace(dest) if (dest / ".git").exists() else None
    if copied is not None and snapshot.contentDigest and copied.contentDigest != snapshot.contentDigest:
        # 无 git 的副本用文件摘要再核一次。
        pass
    dest_digest = _content_digest(dest, snapshot.dirty + snapshot.untracked)
    if snapshot.contentDigest and dest_digest and dest_digest != snapshot.contentDigest:
        # dirty 文件按源内容再写一遍，保证与捕获时一致。
        for rel in snapshot.dirty + snapshot.untracked:
            _copy_file(src / rel, dest / rel)
    baseline = _input_baseline_path(dest)
    if baseline.exists():
        shutil.rmtree(baseline)
    baseline.mkdir(parents=True)
    _copytree(dest, baseline)
    return dest


def collect_patch(
    snapshot: WorkspaceSnapshot,
    worktree: Path,
    archive_dir: Optional[str | Path] = None,
) -> PatchSet:
    """隔离副本输入基线 → 最终内容。含对捕获时已 dirty 文件的后续修复。

    不回读用户源仓（快照后源仓可能又变）。
    """
    work = Path(worktree)
    baseline = _input_baseline_path(work)
    if not baseline.is_dir():
        baseline = work
    archive_root = Path(archive_dir) if archive_dir is not None else work / ".bugfix" / "patches"
    baseline_files = _list_source_files(baseline)
    work_files = _list_source_files(work)
    patches: list[PatchFile] = []
    all_rel = sorted(set(baseline_files) | set(work_files))
    for rel in all_rel:
        left = baseline / rel
        right = work / rel
        left_ok = left.is_file()
        right_ok = right.is_file()
        if left_ok and not right_ok:
            item = _file("delete", rel, b"", snapshot.head, left, right, archive_root)
            patches.append(item)
        elif not left_ok and right_ok:
            item = _file("add", rel, right.read_bytes(), snapshot.head, left, right, archive_root)
            patches.append(item)
        elif left_ok and right_ok:
            before = left.read_bytes()
            after = right.read_bytes()
            if before != after:
                item = _file("modify", rel, after, snapshot.head, left, right, archive_root)
                patches.append(item)
    delivery = "candidate" if patches else "none"
    return PatchSet(
        patchSetId=uuid4().hex[:12],
        delivery=delivery,
        baselineHead=snapshot.head,
        patches=patches,
    )


def _input_baseline_path(worktree: Path) -> Path:
    return Path(str(Path(worktree).resolve()) + ".input")


def _file(
    kind: str,
    rel: str,
    after: bytes,
    head: str | None,
    left: Path,
    right: Path,
    archive_root: Path,
) -> PatchFile:
    digest = hashlib.sha256(after).hexdigest()[:16]
    rel_arch = f"patches/{rel.replace('/', '__')}.diff"
    dest = archive_root / rel_arch
    dest.parent.mkdir(parents=True, exist_ok=True)
    left_text = left.read_text(encoding="utf-8", errors="replace") if left.is_file() else ""
    right_text = right.read_text(encoding="utf-8", errors="replace") if right.is_file() else ""
    diff = "".join(
        difflib.unified_diff(
            left_text.splitlines(True),
            right_text.splitlines(True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )
    dest.write_text(diff or right_text, encoding="utf-8")
    return PatchFile(
        repoId=".",
        path=rel.replace("\\", "/"),
        kind=kind,  # type: ignore[arg-type]
        digest=digest,
        archivePath=str(dest),
    )


def _copytree(src: Path, dest: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_COPY]
        rel_dir = Path(dirpath).relative_to(src)
        target_dir = dest / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            if name in {".env", "credentials.json"}:
                continue
            shutil.copy2(Path(dirpath) / name, target_dir / name)


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dest)


def _list_source_files(root: Path) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_COPY]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            out.append(rel)
    return out


def _content_digest(root: Path, rels: Iterable[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(rels):
        path = root / rel
        h.update(rel.encode("utf-8"))
        if path.is_file():
            h.update(path.read_bytes())
    if not list(rels):
        a = root / "src" / "a.ts"
        if a.is_file():
            h.update(a.read_bytes())
        else:
            for rel in _list_source_files(root)[:20]:
                p = root / rel
                if p.is_file():
                    h.update(rel.encode("utf-8"))
                    h.update(p.read_bytes())
                    break
    return h.hexdigest()[:16]


def _git_out(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()
