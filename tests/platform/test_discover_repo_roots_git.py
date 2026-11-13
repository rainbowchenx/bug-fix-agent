"""repoRoots = outermost git only (no package.json / container heuristic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bugfix_platform.agents.cartographer.detect import (
    NoGitRepoError,
    discover_repo_roots,
    is_git_repo,
)
from tests.helpers import ensure_git_repo


def test_is_git_repo_dir_and_gitfile(tmp_path: Path):
    assert is_git_repo(tmp_path) is False
    ensure_git_repo(tmp_path)
    assert is_git_repo(tmp_path) is True
    other = tmp_path / "sub"
    other.mkdir()
    (other / ".git").write_text("gitdir: ../.git\n", encoding="utf-8")
    assert is_git_repo(other) is True


def test_workdir_is_repo_returns_dot_only(tmp_path: Path):
    """transport / peitao：workDir 自身是仓，不把子目录升成根。"""
    ensure_git_repo(tmp_path)
    nested = tmp_path / "vendor" / "lib"
    ensure_git_repo(nested)  # 模拟误嵌套；命中 workDir 后停探
    (tmp_path / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
    roots = discover_repo_roots(tmp_path)
    assert [r.path for r in roots] == ["."]
    assert roots[0].gitHead


def test_sibling_repos_under_shell(tmp_path: Path):
    """led：壳目录无 .git，两个并列子仓。"""
    a = ensure_git_repo(tmp_path / "calibration-subsystem")
    b = ensure_git_repo(tmp_path / "calibrationtool")
    (a / "package.json").write_text('{"name":"koa"}\n', encoding="utf-8")
    # calibrationtool 无顶层 package.json，只有 electron/web —— 纯 git 仍能发现
    (b / "electron").mkdir()
    (b / "electron" / "package.json").write_text('{"name":"e"}\n', encoding="utf-8")
    roots = discover_repo_roots(tmp_path)
    assert sorted(r.path for r in roots) == ["calibration-subsystem", "calibrationtool"]


def test_shell_with_one_inner_repo(tmp_path: Path):
    """hct：外层壳 + 里层真仓；不把壳当根。"""
    shell = tmp_path / "hct-shell"
    shell.mkdir()
    (shell / "README.md").write_text("shell\n", encoding="utf-8")
    host = ensure_git_repo(shell / "hct")
    (host / "package.json").write_text('{"name":"hct"}\n', encoding="utf-8")
    # 仓内 submodule 占位：有 .git 也不该被扫到（只看直接子目录）
    ensure_git_repo(host / "src" / "AppA")
    roots = discover_repo_roots(shell)
    assert [r.path for r in roots] == ["hct"]


def test_no_git_hard_fails(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name":"shell"}\n', encoding="utf-8")
    nested = tmp_path / "app"
    nested.mkdir()
    (nested / "package.json").write_text('{"name":"app"}\n', encoding="utf-8")
    with pytest.raises(NoGitRepoError, match="no git repo"):
        discover_repo_roots(tmp_path)


def test_electron_container_fixture():
    root = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "repos" / "electron-container"
    roots = discover_repo_roots(root)
    assert sorted(r.path for r in roots) == ["calibration-subsystem", "calibrationtool"]
