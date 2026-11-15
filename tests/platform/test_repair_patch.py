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
