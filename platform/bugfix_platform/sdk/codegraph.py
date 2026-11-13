"""Agent-2 / Agent-3 CodeGraph ensure + MCP mount (@colbymchenry/codegraph).

默认：目标仓有 ``.codegraph/`` 就用；没有就 ``codegraph init`` 建本地索引；
两端 SDK 会话都挂 ``codegraph serve --mcp``。可用 ``BUGFIX_CODEGRAPH=0`` 关掉。

CLI 版本差异必须自己处理，不能让用户去读报错：

- ``init -y``（非交互）**1.6.0 才加**；老版本直接 ``error: unknown option '-y'``
- 0.9.6 的 ``init`` 默认不建索引，要补 ``-i``；0.9.9+ 起默认就建（``-i`` 变已废弃）

所以先探版本、按版本选参数；版本太旧就自己升（``BUGFIX_CODEGRAPH_AUTO_UPGRADE=0`` 可关）。
"""

from __future__ import annotations

import os
import re
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
_PACKAGE = "@colbymchenry/codegraph"
# ``init -y`` 从 1.6.0 开始存在；低于它的版本会拒绝这个参数。
MIN_CODEGRAPH_VERSION = (1, 6, 0)
# 0.9.9 起 ``init`` 默认建索引，之前要显式 ``-i``。
DEFAULT_INDEX_SINCE = (0, 9, 9)


@dataclass
class CodeGraphStatus:
    """一次 ensure 的结果，供 Agent-2/3 挂 MCP / 写 capabilities。"""

    ready: bool
    roots: list[str] = field(default_factory=list)
    """已有索引的绝对路径（workDir 或子仓根）。"""
    initialized: list[str] = field(default_factory=list)
    """本次新跑 ``init`` 的路径。"""
    bin: Optional[str] = None
    version: Optional[str] = None
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

    def mcp_option_kwargs(self, work_dir: str) -> dict[str, Any]:
        """Merge into ``ClaudeAgentOptions``; empty when MCP cannot be mounted.

        Sets ``mcp_servers`` plus ``strict_mcp_config`` so the session only sees
        the CodeGraph server we started, not the user's global MCP mix.
        """
        servers = self.mcp_servers(work_dir)
        if not servers:
            return {}
        return {"mcp_servers": servers, "strict_mcp_config": True}


def codegraph_enabled() -> bool:
    raw = (os.environ.get("BUGFIX_CODEGRAPH") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disable", "disabled")


def codegraph_auto_init() -> bool:
    raw = (os.environ.get("BUGFIX_CODEGRAPH_INIT") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disable", "disabled")


def codegraph_auto_upgrade() -> bool:
    raw = (os.environ.get("BUGFIX_CODEGRAPH_AUTO_UPGRADE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disable", "disabled")


def parse_version(raw: str | None) -> tuple[int, ...]:
    """``codegraph 0.9.6`` / ``0.9.6`` → ``(0, 9, 6)``；认不出返回 ``()``。"""
    found = re.findall(r"\d+", str(raw or ""))
    if not found:
        return ()
    return tuple(int(x) for x in found[:3])


def probe_codegraph_version(bin_path: str, timeout_sec: int = 20) -> Optional[str]:
    """跑 ``codegraph --version``；拿不到就 ``None``（策略上按最保守处理）。"""
    try:
        proc = subprocess.run(
            [bin_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    text = ((proc.stdout or "") + " " + (proc.stderr or "")).strip()
    match = re.search(r"\d+\.\d+(?:\.\d+)?", text)
    return match.group(0) if match else None


def init_args_for_version(version: str | None) -> list[str]:
    """按 CLI 版本挑 ``init`` 参数——不知道版本时给最保守的（不传未知开关）。"""
    parsed = parse_version(version)
    if parsed and parsed >= MIN_CODEGRAPH_VERSION:
        return ["init", "-y"]  # 非交互：吞掉嵌套仓 / watch 两个提问，否则子进程无 TTY 会挂
    if parsed and parsed < DEFAULT_INDEX_SINCE:
        return ["init", "-i"]  # 0.9.6：init 建目录但不建索引
    return ["init"]


def _npm_cmd(argv: Sequence[str]) -> list[str]:
    """Windows 的 npm 是 ``npm.CMD``，不能直接 CreateProcess，要过 cmd /c。"""
    npm = shutil.which("npm")
    if not npm:
        return []
    if os.name == "nt" and npm.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", npm, *argv]
    return [npm, *argv]


def upgrade_codegraph(timeout_sec: int = 300) -> tuple[bool, str]:
    """``npm i -g @colbymchenry/codegraph@latest``；返回 (成功, 说明)。"""
    argv = _npm_cmd(["install", "-g", f"{_PACKAGE}@latest"])
    if not argv:
        return False, "npm not found on PATH"
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"npm install timed out after {timeout_sec}s"
    except OSError as err:
        return False, f"npm install failed: {err}"
    if proc.returncode != 0:
        return False, _npm_error_line(proc.stderr or proc.stdout or "", proc.returncode)[:300]
    return True, "npm install ok"


def _npm_error_line(text: str, returncode: int) -> str:
    """从 npm 输出里挑一行真正说明原因的（尾部往往是 "see the log"）。"""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for marker in ("npm error", "npm ERR!", "EPERM", "EACCES", "ENOTFOUND"):
        for ln in lines:
            if marker in ln:
                return ln
    return lines[-1] if lines else f"npm exit {returncode}"


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
    version: str | None = None,
) -> tuple[bool, str]:
    """``codegraph init``；成功或已有索引返回 True。

    参数按 CLI 版本选（:func:`init_args_for_version`）：``-y`` 只有 1.6.0+ 认，
    0.9.6 要 ``-i`` 才会建索引。版本未知时先不带开关，失败消息里若报
    ``unknown option`` 再退一层重试，不把用户的版本差异变成硬错误。
    """
    path = Path(root).resolve()
    if has_codegraph_index(path):
        return True, "already indexed"
    tried = init_args_for_version(version)
    ok, msg = _run_init(path, bin_path=bin_path, argv=tried, timeout_sec=timeout_sec)
    if ok or not _rejected_option(msg):
        return ok, msg
    # 版本探不到 / 比预期新：退到最保守的 ``init``，再不行补 ``-i``（老版建索引）。
    for fallback in (["init"], ["init", "-i"]):
        if fallback == tried:
            continue
        ok, msg = _run_init(path, bin_path=bin_path, argv=fallback, timeout_sec=timeout_sec)
        if ok or not _rejected_option(msg):
            return ok, msg
    return False, msg


def _rejected_option(msg: str) -> bool:
    low = (msg or "").lower()
    return "unknown option" in low or "unknown argument" in low


def _run_init(
    path: Path, *, bin_path: str, argv: list[str], timeout_sec: int
) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [bin_path, *argv, str(path)],
            cwd=str(path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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
        return False, f"codegraph {' '.join(argv)} timed out after {timeout_sec}s"
    except OSError as err:
        return False, f"codegraph {' '.join(argv)} failed: {err}"
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
    - CLI 版本低于 :data:`MIN_CODEGRAPH_VERSION` 且允许 → 自动 ``npm i -g``（同一个 bin 路径）
    - 否则若允许 init 且找到 ``codegraph`` 二进制 → 按版本选参数的 ``init``
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
    version = probe_codegraph_version(bin_path) if bin_path else None

    if bin_path and _needs_upgrade(version) and do_init:
        if not codegraph_auto_upgrade():
            notes.append(
                f"codegraph {version} < {_ver(MIN_CODEGRAPH_VERSION)} and "
                "BUGFIX_CODEGRAPH_AUTO_UPGRADE off; using legacy init flags"
            )
        else:
            ok, msg = upgrade_codegraph()
            notes.append(f"upgrade {version or 'unknown'} -> latest: {msg}")
            if ok:
                version = probe_codegraph_version(bin_path) or version
                if _needs_upgrade(version):
                    notes.append(f"still {version} after upgrade; using legacy init flags")

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
        ok, msg = init_codegraph(path, bin_path=bin_path, version=version)
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
        version=version,
        detail=detail,
    )


def _ver(parsed: tuple[int, ...]) -> str:
    return ".".join(str(x) for x in parsed) or "?"


def _needs_upgrade(version: str | None) -> bool:
    """版本未知也算需要（宁可升一次，也不要拿未知开关去试）。"""
    parsed = parse_version(version)
    return not parsed or parsed < MIN_CODEGRAPH_VERSION
