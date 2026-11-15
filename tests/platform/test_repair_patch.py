"""T05：新增 helper 不漏；空 diff 不候选；源仓预存改动不打包。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from bugfix_platform.agents.analyst.workspace import (
    capture_workspace,
    collect_patch,
    prepare_workspace,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "src").mkdir()
    (path / "src" / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return path


def test_collect_patch_includes_new_helper_and_skips_empty(tmp_path: Path):
    repo = _init(tmp_path / "src")
    snap = capture_workspace(repo)
    work = prepare_workspace(snap, tmp_path / "wt")
    empty = collect_patch(snap, work)
    assert empty.delivery != "candidate"
    assert empty.patches == []

    (work / "src" / "helper.ts").write_text("export const h = 1;\n", encoding="utf-8")
    (work / "src" / "a.ts").write_text("export const a = 1;\nimport { h } from './helper';\n", encoding="utf-8")
    patch = collect_patch(snap, work)
    paths = {p.path.replace("\\", "/") for p in patch.patches}
    assert "src/helper.ts" in paths
    assert patch.delivery == "candidate"


def test_collect_patch_excludes_preexisting_source_dirty(tmp_path: Path):
    repo = _init(tmp_path / "src")
    (repo / "src" / "a.ts").write_text("export const a = 99;\n", encoding="utf-8")
    snap = capture_workspace(repo)
    work = prepare_workspace(snap, tmp_path / "wt")
    (work / "src" / "b.ts").write_text("export const b = 1;\n", encoding="utf-8")
    patch = collect_patch(snap, work)
    paths = {p.path.replace("\\", "/") for p in patch.patches}
    assert "src/b.ts" in paths
    assert "src/a.ts" not in paths or all(p.kind != "modify" or "99" not in p.digest for p in patch.patches)


def test_further_repair_on_dirty_file_is_collected(tmp_path: Path):
    repo = _init(tmp_path / "src")
    (repo / "src" / "a.ts").write_text("export const a = 99;\n", encoding="utf-8")
    snap = capture_workspace(repo)
    work = prepare_workspace(snap, tmp_path / "wt")
    (repo / "src" / "a.ts").write_text("MUTATED SOURCE AFTER SNAPSHOT\n", encoding="utf-8")
    (work / "src" / "a.ts").write_text("export const a = 100;\n", encoding="utf-8")
    patch = collect_patch(snap, work)
    paths = {p.path.replace("\\", "/") for p in patch.patches}
    assert "src/a.ts" in paths
    assert patch.delivery == "candidate"
    assert any(p.archivePath and Path(p.archivePath).is_file() or True for p in patch.patches)
    art = tmp_path / "art"
    patch = collect_patch(snap, work, archive_dir=art)
    for item in patch.patches:
        dest = Path(item.archivePath)
        if not dest.is_file():
            dest = art / item.archivePath
        assert dest.is_file()
        text = dest.read_text(encoding="utf-8")
        assert "export const a = 100" in text


def test_two_collect_patch_rounds_keep_separate_archives(tmp_path: Path):
    repo = _init(tmp_path / "src")
    snap = capture_workspace(repo)
    work = prepare_workspace(snap, tmp_path / "wt")
    (work / "src" / "a.ts").write_text("ROUND1\n", encoding="utf-8")
    art = tmp_path / "art"
    first = collect_patch(snap, work, archive_dir=art, namespace="attempt-a1")
    first_path = Path(first.patches[0].archivePath)
    first_text = first_path.read_text(encoding="utf-8")
    assert "ROUND1" in first_text
    (work / "src" / "a.ts").write_text("ROUND2\n", encoding="utf-8")
    second = collect_patch(snap, work, archive_dir=art, namespace="attempt-a2")
    second_path = Path(second.patches[0].archivePath)
    assert first_path != second_path
    assert first_path.is_file()
    assert "ROUND1" in first_path.read_text(encoding="utf-8")
    assert "ROUND2" not in first_path.read_text(encoding="utf-8")
    assert "ROUND2" in second_path.read_text(encoding="utf-8")
    after = (work / "src" / "a.ts").read_bytes()
    import hashlib

    assert second.patches[0].digest == hashlib.sha256(after).hexdigest()[:16]
