"""定位 ``claude.exe``：优先用宿主应用自带的那份，避免把 356 MB 打进包里。

## 背景

``claude-agent-sdk`` 的 wheel 有 179 MB，解压后 357 MB —— 其中 356 MB 是
``claude_agent_sdk/_bundled/claude.exe``，纯 Python 代码只有 0.5 MB。

Nexas OS 自己就带了一份 ``claude.exe``（``resources/code-sprite-cli/claude.exe``），
大概率能直接用。所以打包时只带 SDK 的 Python 代码（0.5 MB），运行时来这里找 CLI。

另外 Artifactory 上那个 179 MB 的 wheel 需要认证（401），内网环境根本装不下来 ——
这也是为什么要绕开 pip 装 SDK。

## 查找顺序

1. **显式环境变量** ``BUGFIX_CLAUDE_CLI`` —— 手工指定，最高优先级
2. **PATH 里的 claude.exe** —— 用户自己装过 Claude Code 的情况
3. **SDK 自带的 bundled** —— 如果有
4. **向上遍历父进程提权目录** —— 从当前进程往上找 ``Nexas OS.exe``、
   ``Electron.exe`` 之类，取它所在目录下的 ``resources/code-sprite-cli/claude.exe``

第 4 条是关键：Nexas 用 ``t.cwd || e.workspace`` 作为 spawn 的 cwd，但不会把
executable 路径写进环境变量，所以只能顺着父进程链往上找。

## 副作用

找到后会写进 ``os.environ["PATH"]`` 的前面 —— SDK 的 ``_find_cli`` 只认
PATH 里的绝对路径条目。这样 SDK 自己就能解析到，不用打补丁改它的内部逻辑。
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

__all__ = [
    "apply_cli_path",
    "cli_path_option",
    "cli_supports_hook_on_failure",
    "ensure_claude_cli_on_path",
    "find_claude_cli",
    "hook_on_failure_supported",
]
_EXE_NAME = "claude.exe"
_MAX_DEPTH = 8


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _win_exe_path(pid: int) -> Optional[str]:
    """Win32 ``QueryFullProcessImageNameW``：进程 PID → 可执行文件全路径。"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = ctypes.c_ulong(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value or None
            return None
        finally:
            k32.CloseHandle(handle)
    except (AttributeError, OSError):
        return None


def _win_parent_pid(pid: int) -> Optional[int]:
    """取父进程 PID（Toolhelp32 快照，不依赖 psutil/wmic）。"""
    class _Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap in (-1, 0xFFFFFFFFFFFFFFFF):
            return None
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.th32ProcessID == pid:
                    return int(entry.th32ParentProcessID) or None
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
            return None
        finally:
            k32.CloseHandle(snap)
    except (AttributeError, OSError):
        return None


def _looks_like_host_app(exe: str) -> bool:
    """判断这个可执行文件是不是承载我们的宿主应用。

    只认 Electron 常见的进程名。python.exe / bash.exe / cmd.exe 这些是中间层，
    跳过；命中了才去它所在目录里找 resources/。
    """
    name = Path(exe).name.lower()
    return any(
        token in name
        for token in ("electron", "nexas", "cursor", "code", "claude")
    )


def _exe_from_cmd_shim(shim: Path) -> Optional[Path]:
    """从 npm 的 ``claude.CMD`` 垫片里读出它真正调用的 ``claude.exe``。

    npm 全局安装会生成一个批处理垫片，内容形如::

        @ECHO off
        GOTO start
        :find_dp0
        SET dp0=%~dp0
        EXIT /b
        :start
        SETLOCAL
        CALL :find_dp0
        "%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*

    真正的 exe 在子目录里，不在垫片旁边。SDK 会拒绝直接跑 .CMD（CreateProcess
    不能执行批处理脚本），所以必须解析出 exe。

    解析策略：找第一行里带引号的 ``.exe`` 路径，把 ``%dp0%`` 替换成垫片所在目录。
    找不到就返回 ``None``，让调用方继续用别的分支。
    """
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    match = re.search(r'"([^"]*claude\.exe)"', text, re.IGNORECASE)
    if not match:
        return None

    raw = match.group(1).strip()
    # %dp0% / %~dp0 都表示「垫片所在目录」，可能带结尾反斜杠
    raw = re.sub(r"%[~]?dp0%[\\/]?", "", raw, flags=re.IGNORECASE)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = shim.parent / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    return resolved if _is_file(resolved) else None


def _cli_beside_host_app(host_exe: str) -> list[Path]:
    """宿主应用目录下可能的 claude.exe 位置。

    Nexas 的实际布局（asar 里打包时的 extraResources）::

        <安装目录>/Nexas OS.exe
        <安装目录>/resources/code-sprite-cli/claude.exe
    """
    root = Path(host_exe).parent
    return [
        root / "resources" / "code-sprite-cli" / _EXE_NAME,
        root / "resources" / _EXE_NAME,
        root / _EXE_NAME,
        # 开发模式：electron 目录下
        root / ".." / "resources" / "code-sprite-cli" / _EXE_NAME,
    ]


def _cli_beside_runner() -> Optional[Path]:
    """从 ``langgraph_runner.py`` 自身的位置推 ``claude.exe``。

    这是**最可靠**的一条：Nexas 用 ``process.resourcesPath`` 定位 runner，所以
    runner 一定在 ``<安装目录>/resources/langgraph_runner.py``，而 claude.exe 在
    ``<安装目录>/resources/code-sprite-cli/claude.exe`` —— 同一个 ``resources``
    下的兄弟目录。

    不依赖父进程链（那条在用户从终端启动、或中间隔了 shell 垫片时会断），
    也不依赖 PATH（版本不可控）。
    """
    import sys as _sys

    # ① sys.argv[0] 是 runner.py 的绝对路径
    candidates: list[Path] = []
    argv0 = getattr(_sys, "argv", [""])[0] if getattr(_sys, "argv", None) else ""
    if argv0 and argv0.lower().endswith(".py"):
        candidates.append(Path(argv0))

    # ② 主模块的 __file__（被 runpy/exec 启动时 argv[0] 可能不是脚本路径）
    main_mod = _sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", None)
    if isinstance(main_file, str) and main_file.lower().endswith(".py"):
        candidates.append(Path(main_file))

    for script in candidates:
        try:
            resources = script.resolve().parent
        except OSError:
            continue
        # resources/langgraph_runner.py → resources/
        for candidate in (
            resources / "code-sprite-cli" / _EXE_NAME,
            resources / _EXE_NAME,
        ):
            if _is_file(candidate):
                return candidate.resolve()
        # 开发模式下 runner 在 <repo>/resources/，claude.exe 可能在上层
        for candidate in (
            resources.parent / "resources" / "code-sprite-cli" / _EXE_NAME,
        ):
            if _is_file(candidate):
                return candidate.resolve()
    return None


def _from_process_tree() -> Optional[Path]:
    """顺着父进程链找宿主应用，再取它旁边的 claude.exe。"""
    if sys.platform != "win32":
        return None
    pid = os.getpid()
    for _ in range(_MAX_DEPTH):
        parent = _win_parent_pid(pid)
        if not parent:
            return None
        pid = parent
        exe = _win_exe_path(pid)
        if not exe:
            return None
        if not _looks_like_host_app(exe):
            continue
        for candidate in _cli_beside_host_app(exe):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if _is_file(resolved):
                return resolved
    return None


def find_claude_cli() -> Optional[Path]:
    """按优先级找 ``claude.exe``；找不到返回 ``None``。

    顺序刻意把**宿主应用自带的**排在 PATH 前面：

    - 用户本地 npm 装的 Claude Code 版本不可控，可能是很老的版本
      （老 CLI 不认新 SDK 传的 ``--json-schema`` 之类参数就直接失败）
    - Nexas 自带的 ``claude.exe`` 随客户端发布，所有用户版本一致

    所以：显式指定 → 宿主应用 → PATH → SDK 自带。
    """
    # ① 显式指定
    explicit = (os.environ.get("BUGFIX_CLAUDE_CLI") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if _is_file(candidate):
            return candidate.resolve()

    # ② 宿主应用自带的（版本可控，所有用户一致）
    #    先试 runner 自身位置（最可靠），再退回父进程链。
    host_cli = _cli_beside_runner() or _from_process_tree()
    if host_cli is not None:
        return host_cli

    # ③ PATH（用户自己装的，版本不可控）
    found = shutil.which("claude")
    if found:
        candidate = Path(found)
        # Windows 上 npm 装出来的是 claude.CMD 垫片，SDK 明确拒收批处理文件。
        # 两种情形：
        #   - 同目录有 claude.exe：直接用
        #   - 只有 .CMD：读它内容里引用的真实 exe 路径
        if sys.platform != "win32":
            return candidate.resolve()
        if candidate.suffix.lower() == ".exe":
            return candidate.resolve()
        exe_sibling = candidate.with_suffix(".exe")
        if _is_file(exe_sibling):
            return exe_sibling.resolve()
        from_shim = _exe_from_cmd_shim(candidate)
        if from_shim is not None:
            return from_shim

    # ④ SDK 自带
    try:
        bundled = Path(__file__).parent / "_bundled" / _EXE_NAME
        if _is_file(bundled):
            return bundled.resolve()
    except OSError:
        pass

    return None


def cli_supports_hook_on_failure(cli: Optional[Path] = None) -> bool:
    """这个 ``claude.exe`` 是否支持 hook 的 ``onFailure`` 字段。

    SDK 0.2.182 会给 hook 配置带上 ``onFailure: "block"``，但老版本 CLI 不认这个
    字段，会在 initialize 阶段直接报错::

        The process answering initialize does not honor on_failure on hook
        matchers, so a hook that fails would not block.

    实测分界：2.1.314 不支持，2.1.326 支持。所以这里按版本号判断，
    不支持时调用方要退化成不带 ``on_failure`` 的 HookMatcher。

    探测失败（CLI 跑不起来、输出解析不了）按**不支持**处理 —— 宁可少一层保护，
    也不要整个 SDK 会话起不来。
    """
    target = cli or find_claude_cli()
    if target is None:
        return False
    try:
        proc = subprocess.run(
            [str(target), "--version"],
            capture_output=True,
            timeout=20,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", proc.stdout or proc.stderr or "")
    if not match:
        return False
    version = tuple(int(x) for x in match.groups())
    return version >= _HOOK_ON_FAILURE_MIN_VERSION


# 实测：2.1.314 不支持 onFailure，2.1.326 支持。取 2.1.320 作为保守分界。
_HOOK_ON_FAILURE_MIN_VERSION = (2, 1, 320)


def hook_on_failure_supported() -> bool:
    """进程内缓存的版本判断（一次会话只跑一次 ``--version``）。"""
    global _ON_FAILURE_CACHE
    if _ON_FAILURE_CACHE is None:
        _ON_FAILURE_CACHE = cli_supports_hook_on_failure()
    return _ON_FAILURE_CACHE


_ON_FAILURE_CACHE: Optional[bool] = None


def ensure_claude_cli_on_path() -> Optional[Path]:
    """确保 SDK 能解析到 ``claude.exe``；返回实际使用的路径（找不到则 ``None``）。

    SDK 的 ``SubprocessCLITransport._find_cli()`` 只看两处：包内的 ``_bundled/``
    和 ``PATH`` 里的绝对目录。我们不带 bundled，所以把找到的目录塞进 PATH 最前面。

    **但 PATH 注入不可靠**：``ClaudeAgentOptions`` 在构造时不会解析 CLI，真正的
    查找发生在 ``connect()``，那时代码可能已经被别处的 ``os.environ`` 快照覆盖
    （实测在 ``langgraph_runner.py`` 的 spec 加载路径下就失效了）。所以调用方还应
    把这里返回的路径显式传给 ``ClaudeAgentOptions(cli_path=...)``。

    幂等：已经有了就不重复插。
    """
    return apply_cli_path()


def apply_cli_path() -> Optional[Path]:
    """定位 CLI 并注入 PATH；返回路径供 ``ClaudeAgentOptions(cli_path=...)`` 使用。"""
    cli = find_claude_cli()
    if cli is None:
        return None
    directory = str(cli.parent)
    parts = [p for p in (os.environ.get("PATH") or "").split(os.pathsep) if p]
    if directory not in parts:
        os.environ["PATH"] = os.pathsep.join([directory, *parts])
    return cli


def cli_path_option() -> dict[str, str]:
    """构造 ``ClaudeAgentOptions(cli_path=...)`` 需要的 kwargs；找不到返回空 dict。

    空 dict 让调用方的 ``kwargs.update(...)`` 保持无副作用，SDK 继续走它自己的
    查找逻辑（例如构建机装了完整 wheel 时命中 ``_bundled``）。
    """
    cli = find_claude_cli()
    return {"cli_path": str(cli)} if cli is not None else {}