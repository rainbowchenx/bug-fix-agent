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
    monkeypatch.delenv("BUGFIX_CODEGRAPH", raising=False)
    monkeypatch.setenv("BUGFIX_CODEGRAPH_INIT", "0")
    db_dir = tmp_path / ".codegraph"
    db_dir.mkdir()
    (db_dir / "codegraph.db").write_bytes(b"x" * 64)
    bin_path = resolve_codegraph_bin()
    if not bin_path:
        monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", "/usr/bin/true")
        bin_path = "/usr/bin/true"
    else:
        monkeypatch.setenv("BUGFIX_CODEGRAPH_BIN", bin_path)
    st = ensure_codegraph(tmp_path, init_missing=False)
    assert st.ready is True
    assert str(tmp_path.resolve()) in st.roots
    mcp = st.mcp_servers(str(tmp_path))
    assert "codegraph" in mcp
    assert mcp["codegraph"]["args"][:2] == ["serve", "--mcp"]


@pytest.mark.skipif(shutil.which("codegraph") is None, reason="codegraph CLI not installed")
def test_init_creates_index(tmp_path: Path):
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


def test_status_mcp_empty_when_not_ready():
    st = CodeGraphStatus(ready=False, bin="/tmp/codegraph")
    assert st.mcp_servers("/tmp/proj") == {}
