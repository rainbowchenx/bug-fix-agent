"""Agent-2 CodeGraph ensure + MCP mount (@colbymchenry/codegraph).

默认：目标仓有 ``.codegraph/`` 就用；没有就 ``codegraph init -y`` 建本地索引；
SDK 会话挂 ``codegraph serve --mcp``。可用 ``BUGFIX_CODEGRAPH=0`` 关掉。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence


# Claude Code / Agent SDK 常见 MCP 工具名（含 mcp__ 前缀形态）。
CODEGRAPH_MCP_TOOLS = (
    "codegraph_explore",
    "codegraph_node",
    "codegraph_query",
    "codegraph_callers",
    "codegraph_callees",
    "codegraph_impact",
    "mcp__codegraph__codegraph_explore",
    "mcp__codegraph__codegraph_node",
    "mcp__codegraph__codegraph_query",
    "mcp__codegraph__codegraph_callers",
    "mcp__codegraph__codegraph_callees",
    "mcp__codegraph__codegraph_impact",
)

_DB_NAME = "codegraph.db"
_INDEX_DIR = ".codegraph"


@dataclass
class CodeGraphStatus:
    """一次 ensure 的结果，供 cartography 挂 MCP / 写 capabilities。"""

    ready: bool
    roots: list[str] = field(default_factory=list)
    """已有索引的绝对路径（workDir 或子仓根）。"""
    initialized: list[str] = field(default_factory=list)
    """本次新跑 ``init`` 的路径。"""
    bin: Optional[str] = None
    detail: Optional[str] = None
    disabled: bool = False

    def mcp_servers(self, work_dir: str) -> dict[str, Any]:
        """SDK ``ClaudeAgentOptions.mcp_servers`` 条目；未就绪则空。"""
        if not self.ready or not self.bin:
            return {}
        # 以 workDir 为 MCP 默认工程；子仓查询靠工具参数 projectPath。
        return {
            "codegraph": {
                "type": "stdio",
                "command": self.bin,
                "args": ["serve", "--mcp", "-p", str(Path(work_dir).resolve())],
                "env": {"CODEGRAPH_TELEMETRY": os.environ.get("CODEGRAPH_TELEMETRY", "0")},
            }
        }


def codegraph_enabled() -> bool:
    raw = (os.environ.get("BUGFIX_CODEGRAPH") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disable", "disabled")


def codegraph_auto_init() -> bool:
    raw = (os.environ.get("BUGFIX_CODEGRAPH_INIT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disable", "disabled")


def resolve_codegraph_bin() -> Optional[str]:
    """``BUGFIX_CODEGRAPH_BIN`` → ``PATH`` 上的 ``codegraph``。"""
    override = (os.environ.get("BUGFIX_CODEGRAPH_BIN") or "").strip()
    if override:
        return override
    return shutil.which("codegraph")


def index_dir(root: str | Path) -> Path:
    return Path(root) / _INDEX_DIR


def has_codegraph_index(root: str | Path) -> bool:
    db = index_dir(root) / _DB_NAME
    return db.is_file() and db.stat().st_size > 0


def detect_codegraph_signal(root: str | Path) -> bool:
    """仓内是否已有 CodeGraph 痕迹（索引 / .mcp.json / CLAUDE 提及）。"""
    path = Path(root)
    if has_codegraph_index(path):
        return True
    mcp = path / ".mcp.json"
    if mcp.is_file():
        try:
            text = mcp.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            text = ""
        if "codegraph" in text:
            return True
    for name in ("CLAUDE.md", ".claude/CLAUDE.md"):
        claude = path / name
        if not claude.is_file():
            continue
        try:
            text = claude.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "codegraph" in text.lower() or "code graph" in text.lower():
            return True
    return False


def _candidate_roots(
    work_dir: str | Path, repo_roots: Sequence[Any] | None = None
) -> list[Path]:
    root = Path(work_dir).resolve()
    out: list[Path] = [root]
    for rr in repo_roots or []:
        rel = getattr(rr, "path", None)
        if rel is None and isinstance(rr, dict):
            rel = rr.get("path")
        if not rel or rel in (".", "./"):
            continue
        cand = (root / str(rel)).resolve()
        if cand.is_dir() and cand not in out:
            out.append(cand)
    return out


def init_codegraph(
    root: str | Path,
    *,
    bin_path: str,
    timeout_sec: int = 600,
) -> tuple[bool, str]:
    """``codegraph init -y <root>``；成功或已有索引返回 True。"""
    path = Path(root).resolve()
    if has_codegraph_index(path):
        return True, "already indexed"
    try:
        proc = subprocess.run(
            [bin_path, "init", "-y", str(path)],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={
                **os.environ,
                "CODEGRAPH_TELEMETRY": os.environ.get("CODEGRAPH_TELEMETRY", "0"),
            },
            check=False,
        )
    except FileNotFoundError:
        return False, f"codegraph binary not found: {bin_path}"
    except subprocess.TimeoutExpired:
        return False, f"codegraph init timed out after {timeout_sec}s"
    except OSError as err:
        return False, f"codegraph init failed: {err}"
    if has_codegraph_index(path):
        return True, (proc.stdout or proc.stderr or "init ok").strip()[:300]
    err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300]
    return False, err or f"init failed (exit {proc.returncode})"


def ensure_codegraph(
    work_dir: str | Path,
    repo_roots: Sequence[Any] | None = None,
    *,
    init_missing: bool | None = None,
) -> CodeGraphStatus:
    """探测 + 按需初始化；返回是否可挂 MCP。

    - ``BUGFIX_CODEGRAPH=0`` → disabled
    - 已有 ``.codegraph/codegraph.db`` → ready
    - 否则若允许 init 且找到 ``codegraph`` 二进制 → ``init -y``
    - 找不到二进制 → ready=False（仍可 Grep 降级）
    """
    if not codegraph_enabled():
        return CodeGraphStatus(ready=False, disabled=True, detail="BUGFIX_CODEGRAPH disabled")

    bin_path = resolve_codegraph_bin()
    do_init = codegraph_auto_init() if init_missing is None else init_missing
    roots = _candidate_roots(work_dir, repo_roots)
    ready_roots: list[str] = []
    initialized: list[str] = []
    notes: list[str] = []

    for path in roots:
        if has_codegraph_index(path):
            ready_roots.append(str(path))
            continue
        if not do_init:
            notes.append(f"skip init (disabled): {path}")
            continue
        if not bin_path:
            notes.append("codegraph binary not on PATH; set BUGFIX_CODEGRAPH_BIN or install @colbymchenry/codegraph")
            break
        ok, msg = init_codegraph(path, bin_path=bin_path)
        if ok:
            ready_roots.append(str(path))
            initialized.append(str(path))
            notes.append(f"init {path}: {msg}")
        else:
            notes.append(f"init failed {path}: {msg}")

    ready = bool(ready_roots) and bool(bin_path)
    if ready_roots and not bin_path:
        # 索引在、但没 CLI：MCP 挂不上，Bash/`codegraph` 也不可用。
        notes.append("index present but codegraph binary missing; MCP not mounted")
        ready = False

    detail = "; ".join(notes) if notes else None
    return CodeGraphStatus(
        ready=ready,
        roots=ready_roots,
        initialized=initialized,
        bin=bin_path if ready else bin_path,
        detail=detail,
    )
