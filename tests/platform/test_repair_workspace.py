"""T03：HEAD 相同 dirty 不同可区分；隔离副本不改源仓。"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from bugfix_platform.agents.analyst import workspace
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


def test_capture_digest_includes_clean_tracked_files(tmp_path: Path):
    repo = _init_repo(tmp_path / "src")
    (repo / "src" / "b.ts").write_text("export const b = 1;\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "b"], check=True, capture_output=True)
    first = capture_workspace(repo)
    (repo / "src" / "b.ts").write_text("export const b = 99;\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "b2"], check=True, capture_output=True)
    second = capture_workspace(repo)
    assert first.contentDigest != second.contentDigest


def test_capture_removes_partial_freeze_when_copy_fails(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(workspace.tempfile, "tempdir", str(tmp_path))

    def fail_copy(_src, dest):
        (dest / "partial").write_text("partial copy", encoding="utf-8")
        raise OSError("copy failed")

    monkeypatch.setattr(workspace, "_copytree", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        capture_workspace(repo)
    assert not list(tmp_path.glob("bugfix-freeze-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only files block deletion")
def test_freeze_cleanup_handles_readonly_files_on_windows(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path / "repo")
    monkeypatch.setattr(workspace.tempfile, "tempdir", str(tmp_path))
    source = repo / "src" / "a.ts"
    source.chmod(stat.S_IREAD)
    try:
        with workspace.workspace_snapshot(repo, freeze=True) as snapshot:
            frozen = Path(snapshot.freezeRoot)
            assert not (frozen / "src" / "a.ts").stat().st_mode & stat.S_IWRITE
        assert not frozen.exists()
        assert not source.stat().st_mode & stat.S_IWRITE
    finally:
        source.chmod(stat.S_IWRITE)


def test_snapshot_uses_same_exclusions_as_frozen_copy(tmp_path):
    import shutil
    from bugfix_platform.agents.analyst.workspace import workspace_digest
    repo=_init_repo(tmp_path/'repo')
    (repo/'.env').write_text('TEST_ONLY=dummy\n')
    (repo/'src'/'credentials.json').write_text('{"testOnly":true}')
    snapshot=capture_workspace(repo)
    frozen=Path(snapshot.freezeRoot)
    try:
        assert not (frozen/'.env').exists()
        assert not (frozen/'src'/'credentials.json').exists()
        assert workspace_digest(repo)==workspace_digest(frozen)==snapshot.contentDigest
        prepare_workspace(snapshot,tmp_path/'candidate')
        assert (repo/'.env').read_text()=='TEST_ONLY=dummy\n'
    finally:
        shutil.rmtree(frozen,ignore_errors=True)
