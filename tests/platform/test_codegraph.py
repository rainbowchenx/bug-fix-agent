"""Agent-2 CodeGraph ensure + MCP mount."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bugfix_platform.sdk.codegraph import (
    CODEGRAPH_MCP_TOOLS,
    CodeGraphStatus,
    ensure_codegraph,
    has_codegraph_index,
    init_codegraph,
    resolve_codegraph_bin,
)


def test_mcp_tool_names_include_explore():
    assert "codegraph_explore" in CODEGRAPH_MCP_TOOLS
    assert "mcp__codegraph__codegraph_explore" in CODEGRAPH_MCP_TOOLS


def test_has_index_false_without_db(tmp_path: Path):
    assert has_codegraph_index(tmp_path) is False
    (tmp_path / ".codegraph").mkdir()
    assert has_codegraph_index(tmp_path) is False


def test_ensure_disabled(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BUGFIX_CODEGRAPH", "0")
    st = ensure_codegraph(tmp_path)
    assert st.disabled is True
    assert st.ready is False
    assert st.mcp_servers(str(tmp_path)) == {}


def test_ensure_uses_existing_index(monkeypatch, tmp_path: Path):
    from tests.helpers import ensure_git_repo

    monkeypatch.delenv("BUGFIX_CODEGRAPH", raising=False)
    monkeypatch.setenv("BUGFIX_CODEGRAPH_INIT", "0")
    ensure_git_repo(tmp_path)
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    (db_dir / "codegraph.db").write_bytes(b"x" * 64)
    bin_path = resolve_codegraph_bin()
    if not bin_path:
        monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", "/usr/bin/true")
        bin_path = "/usr/bin/true"
    else:
        monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", bin_path)

    def _fake_stats(bin_path: str, root, timeout_sec: int = 30):
        return {"files": 3, "pending": 0}

    monkeypatch.setattr(
        "bugfix_platform.sdk.codegraph.probe_index_stats", _fake_stats
    )
    st = ensure_codegraph(tmp_path, init_missing=False)
    assert st.ready is True
    assert str(tmp_path.resolve()) in st.roots
    mcp = st.mcp_servers(str(tmp_path))
    assert "codegraph" in mcp
    assert mcp["codegraph"]["args"][:2] == ["serve", "--mcp"]
    assert mcp["codegraph"]["args"][3] == str(tmp_path.resolve())


def test_ensure_skips_empty_index_and_shell_workdir(monkeypatch, tmp_path: Path):
    """壳 workDir 不入 candidate；files=0 的索引不进 MCP。"""
    from bugfix_contracts.code_knowledge import RepoRoot
    from tests.helpers import ensure_git_repo

    monkeypatch.delenv("BUGFIX_CODEGRAPH", raising=False)
    shell = tmp_path / "shell"
    shell.mkdir()
    repo = ensure_git_repo(shell / "app")
    db = repo / ".codegraph"
    db.mkdir()
    (db / "codegraph.db").write_bytes(b"x" * 64)
    monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", "/usr/bin/true")
    monkeypatch.setenv("BUGFIX_CODEGRAPH_INIT", "0")

    def _empty_stats(bin_path: str, root, timeout_sec: int = 30):
        return {"files": 0, "pending": 12}

    monkeypatch.setattr(
        "bugfix_platform.sdk.codegraph.probe_index_stats", _empty_stats
    )
    st = ensure_codegraph(
        shell,
        [RepoRoot(path="app", gitHead="a" * 40)],
        init_missing=False,
    )
    assert st.ready is False
    assert st.roots == []
    assert "index-truncated" in (st.detail or "")
    assert st.mcp_servers(str(shell)) == {}


@pytest.mark.skipif(shutil.which("codegraph") is None, reason="codegraph CLI not installed")
def test_init_creates_index(tmp_path: Path):
    from tests.helpers import ensure_git_repo

    ensure_git_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("export const x = 1;\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"t"}\n', encoding="utf-8")
    bin_path = resolve_codegraph_bin()
    assert bin_path
    ok, _msg = init_codegraph(tmp_path, bin_path=bin_path, timeout_sec=120)
    assert ok is True
    assert has_codegraph_index(tmp_path) is True
    st = ensure_codegraph(tmp_path, init_missing=False)
    assert st.ready is True
    assert st.root_stats[str(tmp_path.resolve())].get("files", 0) > 0


def test_status_mcp_empty_when_not_ready():
    st = CodeGraphStatus(ready=False, bin="/tmp/codegraph")
    assert st.mcp_servers("/tmp/proj") == {}
    assert st.mcp_option_kwargs("/tmp/proj") == {}


def test_mcp_option_kwargs_when_ready():
    st = CodeGraphStatus(ready=True, bin="/usr/bin/codegraph")
    kw = st.mcp_option_kwargs("/tmp/proj")
    assert kw["mcp_servers"]["codegraph"]["args"][:2] == ["serve", "--mcp"]
    assert kw["strict_mcp_config"] is True


# ---------------------------------------------------------------------------
# CLI 版本差异：`-y` 只有 1.6.0+ 认；0.9.6 的 init 要 `-i` 才建索引。
# 老代码无条件 `init -y`，任何 0.9.x/1.5.x 机器上都直接
# `error: unknown option '-y'`，然后静默退回纯 grep。
# ---------------------------------------------------------------------------


def test_init_args_follow_cli_version():
    from bugfix_platform.sdk.codegraph import init_args_for_version

    assert init_args_for_version("0.9.6") == ["init", "-i"]  # 老版不建索引
    assert init_args_for_version("0.9.9") == ["init"]  # 起默认建索引
    assert init_args_for_version("1.5.0") == ["init"]  # 还不认识 -y
    assert init_args_for_version("1.6.0") == ["init", "-y"]
    assert init_args_for_version("1.6.2") == ["init", "-y"]
    assert init_args_for_version(None) == ["init"]  # 不知道版本就别塞开关


def test_parse_version_tolerates_noise():
    from bugfix_platform.sdk.codegraph import parse_version

    assert parse_version("0.9.6") == (0, 9, 6)
    assert parse_version("codegraph 1.6.2\n") == (1, 6, 2)
    assert parse_version("") == ()
    assert parse_version(None) == ()
    assert parse_version("v1.6") == (1, 6)


def test_needs_upgrade(monkeypatch):
    from bugfix_platform.sdk.codegraph import _needs_upgrade

    assert _needs_upgrade("0.9.6") is True
    assert _needs_upgrade("1.5.0") is True
    assert _needs_upgrade("1.6.0") is False
    assert _needs_upgrade("1.6.2") is False
    assert _needs_upgrade(None) is True  # 探不到版本也要升


def test_init_retries_without_rejected_flag(tmp_path: Path, monkeypatch):
    """版本探不到、`-y` 被拒时退到 `init`，而不是把差异变成硬错误。"""
    from bugfix_platform.sdk import codegraph as cg

    calls: list[list[str]] = []

    def fake_run_init(path, *, bin_path, argv, timeout_sec):
        calls.append(argv)
        if "-y" in argv:
            return False, "error: unknown option '-y'"
        return True, "init ok"

    monkeypatch.setattr(cg, "_run_init", fake_run_init)
    ok, msg = cg.init_codegraph(tmp_path, bin_path="codegraph", version=None)
    assert ok is True
    assert calls[0] == ["init"]
    assert all(c == ["init"] or "-y" not in c for c in calls)


def test_npm_error_line_picks_the_real_reason():
    from bugfix_platform.sdk.codegraph import _npm_error_line

    out = (
        "npm warn cleanup Failed to remove some directories\n"
        "npm error code EPERM\n"
        "npm error syscall unlink\n"
        "npm error A complete log of this run can be found in: /x/_logs/y.log\n"
    )
    line = _npm_error_line(out, 1)
    assert "EPERM" in line or "npm error" in line
    assert "complete log" not in line  # 别把“去看日志”当原因报出来
    assert _npm_error_line("", 7) == "npm exit 7"


def test_ensure_upgrades_old_cli_before_init(tmp_path: Path, monkeypatch):
    """0.9.6 → 自动 npm 升级 → 重新探版本 → init 带 -y。"""
    from bugfix_platform.sdk import codegraph as cg
    from tests.helpers import ensure_git_repo

    ensure_git_repo(tmp_path)
    seen: dict[str, object] = {"versions": ["0.9.6", "1.6.2"], "init": []}

    def fake_probe(bin_path, timeout_sec=20):
        return seen["versions"].pop(0) if seen["versions"] else "1.6.2"

    def fake_upgrade(timeout_sec=300):
        seen["upgraded"] = True
        return True, "npm install ok"

    def fake_init(path, *, bin_path, timeout_sec=600, version=None):
        seen["init"].append(version)
        (Path(path) / ".codegraph").mkdir(exist_ok=True)
        (Path(path) / ".codegraph" / "codegraph.db").write_bytes(b"x" * 64)
        return True, "init ok"

    monkeypatch.setattr(cg, "probe_codegraph_version", fake_probe)
    monkeypatch.setattr(cg, "upgrade_codegraph", fake_upgrade)
    monkeypatch.setattr(cg, "init_codegraph", fake_init)
    monkeypatch.setattr(cg, "probe_index_stats", lambda *a, **k: {"files": 2})
    monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", "codegraph")
    monkeypatch.delenv("BUGFIX_CODEGRAPH", raising=False)
    monkeypatch.delenv("BUGFIX_CODEGRAPH_AUTO_UPGRADE", raising=False)

    st = cg.ensure_codegraph(tmp_path)
    assert seen.get("upgraded") is True
    assert seen["init"] == ["1.6.2"]  # init 用的是升级后的版本
    assert st.version == "1.6.2"
    assert "upgrade 0.9.6" in (st.detail or "")
    assert st.ready is True


def test_ensure_skips_upgrade_when_disabled(tmp_path: Path, monkeypatch):
    """关掉自动升级时仍能跑（用老版参数），但要在 detail 里说清楚。"""
    from bugfix_platform.sdk import codegraph as cg
    from tests.helpers import ensure_git_repo

    ensure_git_repo(tmp_path)

    def boom(*a, **k):
        raise AssertionError("must not upgrade when disabled")

    monkeypatch.setattr(cg, "probe_codegraph_version", lambda *a, **k: "0.9.6")
    monkeypatch.setattr(cg, "upgrade_codegraph", boom)
    monkeypatch.setattr(cg, "init_codegraph", lambda *a, **k: (False, "nope"))
    monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", "codegraph")
    monkeypatch.setenv("BUGFIX_CODEGRAPH_AUTO_UPGRADE", "0")
    monkeypatch.delenv("BUGFIX_CODEGRAPH", raising=False)

    st = cg.ensure_codegraph(tmp_path)
    assert st.ready is False
    assert "AUTO_UPGRADE off" in (st.detail or "")
