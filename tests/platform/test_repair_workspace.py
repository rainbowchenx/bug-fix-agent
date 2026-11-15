"""T03：HEAD 相同 dirty 不同可区分；隔离副本不改源仓。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from bugfix_platform.agents.analyst.workspace import capture_workspace, prepare_workspace


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return out.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "src").mkdir()
    (path / "src" / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    return path


def test_same_head_different_dirty_are_distinct(tmp_path: Path):
    repo = _init_repo(tmp_path / "src")
    clean = capture_workspace(repo)
    (repo / "src" / "a.ts").write_text("export const a = 2;\n", encoding="utf-8")
    dirty = capture_workspace(repo)
    assert clean.head == dirty.head
    assert clean.dirty != dirty.dirty or clean.contentDigest != dirty.contentDigest
    assert "src/a.ts" in dirty.dirty or dirty.contentDigest != clean.contentDigest


def test_prepare_workspace_does_not_mutate_source(tmp_path: Path):
    repo = _init_repo(tmp_path / "src")
    (repo / "src" / "a.ts").write_text("export const a = 2;\n", encoding="utf-8")
    before = (repo / "src" / "a.ts").read_text(encoding="utf-8")
    snap = capture_workspace(repo)
    dest = tmp_path / "copy"
    out = prepare_workspace(snap, dest)
    assert out.exists()
    assert (out / "src" / "a.ts").read_text(encoding="utf-8") == before
    assert (repo / "src" / "a.ts").read_text(encoding="utf-8") == before
    (out / "src" / "a.ts").write_text("changed in copy\n", encoding="utf-8")
    assert (repo / "src" / "a.ts").read_text(encoding="utf-8") == before


def test_porcelain_keeps_full_path_for_space_prefixed_modified(tmp_path: Path):
    repo = _init_repo(tmp_path / "src")
    (repo / "src" / "a.ts").write_text("export const a = 2;\n", encoding="utf-8")
    snap = capture_workspace(repo)
    assert "src/a.ts" in snap.dirty
    assert "rc/a.ts" not in snap.dirty


def test_prepare_keeps_captured_bytes_if_source_mutates(tmp_path: Path):
    repo = _init_repo(tmp_path / "src")
    (repo / "src" / "a.ts").write_text("CAPTURED\n", encoding="utf-8")
    snap = capture_workspace(repo)
    (repo / "src" / "a.ts").write_text("MUTATED AFTER SNAPSHOT\n", encoding="utf-8")
    out = prepare_workspace(snap, tmp_path / "copy")
    assert (out / "src" / "a.ts").read_text(encoding="utf-8") == "CAPTURED\n"
