"""Git 快照与隔离工作副本。不修改用户源工作区。"""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4

from bugfix_contracts.repair import PatchFile, PatchSet, WorkspaceSnapshot

from bugfix_platform.workspace_fingerprint import _SKIP_COPY, _SKIP_FILES, _list_source_files, workspace_digest


def capture_workspace(repo_root: Path) -> WorkspaceSnapshot:
    """采集 HEAD、dirty 和内容摘要。源目录只读；同时冻结一份输入副本。"""
    root = Path(repo_root)
    head = (_git_out(root, "rev-parse", "HEAD") or "").strip() or None
    porcelain = _git_out(root, "status", "--porcelain") or ""
    dirty: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].replace("\\", "/")
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if line.startswith("??"):
            untracked.append(path)
        else:
            dirty.append(path)
    digest = workspace_digest(root)
    freeze = Path(tempfile.mkdtemp(prefix="bugfix-freeze-"))
    _copytree(root, freeze)
    freeze_digest = workspace_digest(freeze)
    if digest and freeze_digest != digest:
        shutil.rmtree(freeze, ignore_errors=True)
        raise RuntimeError("source changed while freezing snapshot")
    return WorkspaceSnapshot(
        repoId=str(root.resolve()),
        head=head,
        dirty=dirty,
        untracked=untracked,
        contentDigest=digest,
        capturedAt=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        freezeRoot=str(freeze),
    )


def prepare_workspace(snapshot: WorkspaceSnapshot, destination: Path) -> Path:
    """把已登记基线重放到隔离目录并校验，不改源仓、不回读捕获后的源目录。"""
    src = Path(snapshot.freezeRoot) if snapshot.freezeRoot else Path(snapshot.repoId)
    if not src.is_dir():
        raise RuntimeError("frozen snapshot missing; refuse live recopy")
    dest = Path(destination)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    _copytree(src, dest)
    dest_digest = workspace_digest(dest)
    if snapshot.contentDigest and dest_digest and dest_digest != snapshot.contentDigest:
        raise RuntimeError("workspace copy does not match captured baseline")
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
    namespace: Optional[str] = None,
) -> PatchSet:
    """隔离副本输入基线 → 最终内容。含对捕获时已 dirty 文件的后续修复。

    不回读用户源仓（快照后源仓可能又变）。
    """
    work = Path(worktree)
    baseline = _input_baseline_path(work)
    if not baseline.is_dir():
        baseline = work
    archive_root = Path(archive_dir) if archive_dir is not None else work / ".bugfix" / "patches"
    archive_root = archive_root / (namespace or uuid4().hex[:12])
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
    if patches and not _patches_apply(baseline, patches):
        delivery = "diagnostic"
    bundle_path = _write_bundle(archive_root, patches) if patches else None
    if delivery == "candidate" and bundle_path and not _bundle_applies(baseline, Path(bundle_path)):
        delivery = "diagnostic"
    return PatchSet(
        patchSetId=uuid4().hex[:12],
        delivery=delivery,
        baselineHead=snapshot.head,
        baselineDigest=workspace_digest(baseline),
        bundlePath=bundle_path,
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
    diff = _unified_diff(left, right, rel)
    dest.write_bytes(diff.replace("\r\n", "\n").encode("utf-8"))
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
            if name in _SKIP_FILES:
                continue
            shutil.copy2(Path(dirpath) / name, target_dir / name)


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dest)


def _unified_diff(left: Path, right: Path, rel: str) -> str:
    left_arg = str(left.resolve()) if left.is_file() else os.devnull
    right_arg = str(right.resolve()) if right.is_file() else os.devnull
    try:
        proc = subprocess.run(
            ["git", "diff", "--no-index", "--", left_arg, right_arg],
            capture_output=True,
        )
        text = (proc.stdout or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
        if text.strip():
            return _rewrite_diff_paths(text, rel, left.is_file(), right.is_file())
    except OSError:
        text = ""
    return _difflib_patch(left, right, rel)


def _rewrite_diff_paths(text: str, rel: str, left_exists: bool, right_exists: bool) -> str:
    lines: list[str] = []
    for line in text.splitlines(True):
        if line.startswith("diff --git "):
            line = f"diff --git a/{rel} b/{rel}\n"
        elif line.startswith("--- "):
            line = "--- /dev/null\n" if not left_exists else f"--- a/{rel}\n"
        elif line.startswith("+++ "):
            line = "+++ /dev/null\n" if not right_exists else f"+++ b/{rel}\n"
        lines.append(line)
    return "".join(lines)


def _difflib_patch(left: Path, right: Path, rel: str) -> str:
    left_text = left.read_text(encoding="utf-8", errors="replace") if left.is_file() else ""
    right_text = right.read_text(encoding="utf-8", errors="replace") if right.is_file() else ""
    left_lines = _lines_for_diff(left_text)
    right_lines = _lines_for_diff(right_text)
    body = "".join(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="\n",
        )
    )
    if not body:
        if not left.is_file() and right.is_file():
            numbered = "".join(f"+{line}" for line in right_lines) or "+\n"
            nl = "\\ No newline at end of file\n" if right_text and not right_text.endswith("\n") else ""
            return (
                f"diff --git a/{rel} b/{rel}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{rel}\n"
                f"@@ -0,0 +1,{max(len(right_lines), 1)} @@\n"
                f"{numbered}{nl}"
            )
        return ""
    if left_text and not left_text.endswith("\n"):
        last = left_text.splitlines()[-1]
        body = body.replace(f"-{last}\n", f"-{last}\n\\ No newline at end of file\n", 1)
    if right_text and not right_text.endswith("\n"):
        last = right_text.splitlines()[-1]
        needle = f"+{last}\n"
        if needle in body:
            body = body.replace(needle, needle + "\\ No newline at end of file\n", 1)
    if not left.is_file():
        body = body.replace(f"--- a/{rel}\n", "--- /dev/null\n", 1)
        if "new file mode" not in body:
            body = body.replace(
                f"diff --git a/{rel} b/{rel}\n",
                f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n",
                1,
            )
    if not right.is_file():
        body = body.replace(f"+++ b/{rel}\n", "+++ /dev/null\n", 1)
    return body


def _lines_for_diff(text: str) -> list[str]:
    if not text:
        return []
    lines = text.splitlines(True)
    if not text.endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    return lines


def _write_bundle(archive_root: Path, patches: list[PatchFile]) -> str | None:
    chunks: list[str] = []
    for item in patches:
        src = Path(item.archivePath)
        if not src.is_file():
            continue
        chunk = src.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        if chunk and not chunk.endswith("\n"):
            chunk += "\n"
        chunks.append(chunk)
    if not chunks:
        return None
    dest = Path(archive_root) / "bundle.diff"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes("".join(chunks).encode("utf-8"))
    return str(dest)


def _bundle_applies(baseline: Path, bundle: Path) -> bool:
    check = Path(tempfile.mkdtemp(prefix="bugfix-bundle-"))
    try:
        _copytree(baseline, check)
        proc = subprocess.run(
            ["git", "apply", "--check", str(bundle)],
            cwd=check,
            capture_output=True,
        )
        return proc.returncode == 0
    except OSError:
        return False
    finally:
        shutil.rmtree(check, ignore_errors=True)


def _patches_apply(baseline: Path, patches: list[PatchFile]) -> bool:
    if not patches:
        return True
    check = Path(tempfile.mkdtemp(prefix="bugfix-apply-"))
    try:
        _copytree(baseline, check)
        for item in patches:
            src = Path(item.archivePath)
            if not src.is_file():
                return False
            proc = subprocess.run(
                ["git", "apply", "--check", str(src)],
                cwd=check,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                return False
        return True
    except OSError:
        return False
    finally:
        shutil.rmtree(check, ignore_errors=True)


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
    return proc.stdout or ""
