"""SDK 会话轨迹记录：全量落盘 + stdout 摘要。

## 为什么需要

模型的思考过程、读了哪些文件、工具返回了什么，全都只在 SDK 的消息流里过一遍。
``_drive()`` 以前只挑出纯文本和 ``ResultMessage``，其余（``ThinkingBlock`` /
``ToolUseBlock`` / ``ToolResultBlock``）全部丢弃 —— 出问题时只能看到最后一行
汇总，不知道中间发生了什么。

## 两条输出通道

====================  ==================  ======================================
通道                  容量                 用途
====================  ==================  ======================================
``artifact/logs/``   不限（jsonl 逐条）   事后排查：思考原文、工具参数、工具返回
stdout               64 KB（平台上限）    运行中观感：每轮一行的进度摘要
====================  ==================  ======================================

stdout 那条有硬上限：Nexas 的 ``attachChildHandlers`` 用
``(buffer + text).slice(0, 64*1024)`` 累积，超出部分丢掉。所以摘要必须短 ——
只放轮次、思考字数、工具名，不放工具参数（那是日志文件的活）。

## 为什么 stdout 而不是 stderr

客户端 ``fetchTerminalDetail()`` 返回 ``logText: stdoutBuffer || ...`` ——
界面上显示的日志来自 **stdout**，stderr 只在报错兜底时用。而 stdout 的额度
（64 KB）还是 stderr（16 KB）的四倍。

## 开关

``BUGFIX_TRACE`` 默认**开**（full 级别）。关掉用 ``BUGFIX_TRACE=0``。
日志落在每次 run 自己的 ``artifact_dir/logs/`` 下，不写系统临时目录。

注意 full 级别会记录被分析仓库的源码片段（Read 工具的返回值）。产物目录若会被
收集到共享位置，需要先评估这一点。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = [
    "TraceRecorder",
    "open_recorder",
    "trace_enabled",
    "iter_blocks",
]

# 单行摘要上限：stdout 总共 64 KB，按 20-30 轮估算，每行控在 150 字符内很安全。
_SUMMARY_LINE_MAX = 150

# 工具返回值的截断长度（日志文件里）。Read 一次可能几百 KB，全存没意义。
_TOOL_RESULT_PREVIEW = 4000
_TEXT_PREVIEW = 8000

# 只带心跳、没有信息量的 system 事件。实测一个会话能刷近万条，能把日志撑到 3 MB。
_NOISY_SYSTEM = frozenset({"thinking_tokens"})


def _flags() -> bool:
    raw = (os.environ.get("BUGFIX_TRACE") or "").strip().lower()
    # 默认开；只有显式 0/false/no/off 才关。
    return raw not in ("0", "false", "no", "off")


def trace_enabled() -> bool:
    """轨迹记录是否开启（默认开）。"""
    return _flags()


def iter_blocks(message: Any) -> Iterable[Any]:
    """取出消息里的内容块；``content`` 不是列表时返回空。"""
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return content
    return ()


def _short(text: Any, limit: int) -> str:
    value = str(text or "").replace("\n", "⏎")
    return value if len(value) <= limit else value[: limit - 1] + "…"


class TraceRecorder:
    """一次 SDK 会话的轨迹。

    Parameters
    ----------
    log_dir:
        日志目录（通常是 ``artifact_dir/logs``）。为 ``None`` 时只输出 stdout 摘要。
    name:
        日志文件名主干，形如 ``agent3-BGCM2026102708222``。
    echo_summary:
        是否往 stdout 打进度摘要。关掉用于静默场景（单测）。
    tag:
        stdout 摘要的前缀，用来区分同一进程里的不同会话（如 ``[agent2]``）。
    """

    def __init__(
        self,
        log_dir: Optional[Path | str],
        name: str,
        *,
        echo_summary: bool = True,
        tag: str = "",
        enabled: Optional[bool] = None,
    ) -> None:
        self.enabled = trace_enabled() if enabled is None else enabled
        self.echo_summary = echo_summary
        self.tag = tag
        self._fh = None
        self._path: Optional[Path] = None
        self._turn = 0
        self._turn_thinking = 0
        self._turn_tools: list[str] = []
        self._started = time.monotonic()

        if not self.enabled:
            return
        if log_dir is None:
            return
        try:
            root = Path(log_dir)
            root.mkdir(parents=True, exist_ok=True)
            self._path = root / f"{name}.jsonl"
            self._fh = self._path.open("a", encoding="utf-8")
        except OSError as err:
            # 日志写不了不能影响主流程，降级成只打 stdout。
            print(f"[trace] cannot open log file: {err}", file=sys.stderr, flush=True)
            self._fh = None

    # -- 对外 ---------------------------------------------------------------

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def close(self) -> None:
        self._finish_turn()
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def message(self, message: Any) -> None:
        """记录一条 SDK 消息。

        迭代顺序很关键：``AssistantMessage`` 代表"新的一轮开始"，必须**先**收掉
        上一轮摘要、再递增轮次，最后才展开它的 content 块 —— 否则第一轮的
        思考/工具会被算到第 0 轮。
        """
        if not self.enabled:
            return
        if type(message).__name__ == "AssistantMessage":
            self._finish_turn()
            self._turn += 1
            usage = getattr(message, "usage", None)
            if usage:
                self._write("usage", turn=self._turn, **usage)
        for block in iter_blocks(message):
            self._node(block)
        if type(message).__name__ in ("ResultMessage", "SystemMessage"):
            self._node(message)

    def note(self, kind: str, **fields: Any) -> None:
        """记录一条非消息事件（候选丢弃、校验失败等）。"""
        self._write(kind, **fields)

    # -- 内部 ---------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if not self.echo_summary:
            return
        prefix = f"{self.tag} " if self.tag else ""
        print(f"{prefix}{text[:_SUMMARY_LINE_MAX]}", file=sys.stdout, flush=True)

    def _write(self, kind: str, **fields: Any) -> None:
        if self._fh is None:
            return
        record = {"t": time.strftime("%H:%M:%S"), "kind": kind, **fields}
        try:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._fh.flush()
        except (OSError, TypeError, ValueError):
            pass

    def _finish_turn(self) -> None:
        """一轮结束：把摘要打进 stdout。"""
        if self._turn == 0:
            return
        bits = [f"turn {self._turn}"]
        if self._turn_thinking:
            bits.append(f"think={self._turn_thinking}c")
        if self._turn_tools:
            # 只放工具名，不放参数 —— 参数在日志文件里
            counts: dict[str, int] = {}
            for name in self._turn_tools:
                counts[name] = counts.get(name, 0) + 1
            rendered = " ".join(
                name if n == 1 else f"{name}×{n}" for name, n in counts.items()
            )
            bits.append(rendered)
        self._emit("  ".join(bits))
        self._turn_thinking = 0
        self._turn_tools = []

    def _node(self, block: Any) -> None:
        name = type(block).__name__

        if name == "ThinkingBlock":
            text = getattr(block, "thinking", "") or ""
            self._turn_thinking += len(text)
            self._write("thinking", turn=self._turn, text=_short(text, _TEXT_PREVIEW))
            return

        if name == "TextBlock":
            text = getattr(block, "text", "") or ""
            self._write("text", turn=self._turn, text=_short(text, _TEXT_PREVIEW))
            return

        if name == "ToolUseBlock":
            tool = str(getattr(block, "name", "") or "?")
            self._turn_tools.append(tool)
            self._write(
                "tool_use",
                turn=self._turn,
                name=tool,
                input=getattr(block, "input", {}) or {},
            )
            return

        if name == "ToolResultBlock":
            content = getattr(block, "content", None)
            text = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False, default=str
            )
            self._write(
                "tool_result",
                turn=self._turn,
                ok=not bool(getattr(block, "is_error", False)),
                bytes=len(text or ""),
                preview=_short(text, _TOOL_RESULT_PREVIEW),
            )
            return

        if name == "UserMessage":
            # 工具结果回灌，不单独记（ToolResultBlock 已经记了内容）
            return

        if name == "SystemMessage":
            subtype = getattr(block, "subtype", "") or ""
            # thinking_tokens 是逐 token 的心跳事件（一个会话能刷近万条），
            # 除了把日志撑大没有任何信息量。只留 init / hook 这类有内容的。
            if subtype and subtype not in _NOISY_SYSTEM:
                self._write("system", subtype=subtype, data=getattr(block, "data", {}) or {})
            return

        if name == "ResultMessage":
            # 会话来收尾：不递增轮次，只补一条结果记录。摘要行由 next
            # AssistantMessage 或 close() 收掉，这里不重复打。
            self._write(
                "result",
                subtype=getattr(block, "subtype", None),
                is_error=bool(getattr(block, "is_error", False)),
                cost=getattr(block, "total_cost_usd", None),
                turns=getattr(block, "num_turns", None),
            )
            return


def open_recorder(
    artifact_dir: Optional[str | Path],
    name: str,
    *,
    echo_summary: bool = True,
    tag: str = "",
) -> TraceRecorder:
    """按 ``artifact_dir/logs/`` 开一个记录器。

    ``artifact_dir`` 为空时不写文件，但仍按需打 stdout 摘要。
    """
    log_dir = (Path(artifact_dir) / "logs") if artifact_dir else None
    return TraceRecorder(log_dir, name, echo_summary=echo_summary, tag=tag)