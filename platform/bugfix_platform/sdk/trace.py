"""Record SDK sessions and route live output to the current entry point."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

# 单行摘要上限：stdout 总共 64 KB，按 20-30 轮估算，每行控在 150 字符内很安全。
_SUMMARY_LINE_MAX = 150

# 工具返回值的截断长度（日志文件里）。Read 一次可能几百 KB，全存没意义。
_TOOL_RESULT_PREVIEW = 4000
_TEXT_PREVIEW = 8000

# 只带心跳、没有信息量的 system 事件。实测一个会话能刷近万条，能把日志撑到 3 MB。
_NOISY_SYSTEM = frozenset({"thinking_tokens"})
_TERMINAL_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Separate budgets keep phase transitions visible after verbose output is capped.
# Both fit within the host's 64 KiB stdout buffer.
_NEXAS_LIVE_BYTES = 48 * 1024
_NEXAS_MILESTONE_BYTES = 8 * 1024
_NEXAS_TEXT_CHARS = 1200
TraceMode = Literal["off", "summary", "detailed"]


def _env_mode() -> TraceMode:
    raw = (os.environ.get("BUGFIX_TRACE") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return "off"
    return "detailed" if raw == "detailed" else "summary"


class TraceDisplay:
    def __init__(self, mode: TraceMode, *, stderr: bool = False, nexas: bool = False) -> None:
        self.mode = mode
        self.stderr = stderr
        self.nexas = nexas
        self._remaining = _NEXAS_LIVE_BYTES
        self._milestone_remaining = _NEXAS_MILESTONE_BYTES

    def write(self, text: str, *, milestone: bool = False) -> None:
        if self.mode == "off" or not text:
            return
        stream = sys.stderr if self.stderr else sys.stdout
        text = _TERMINAL_CONTROLS.sub("", text.replace("\r\n", "\n"))
        if self.nexas:
            size = len(text.encode("utf-8", errors="replace"))
            if milestone:
                if size > self._milestone_remaining:
                    return
                self._milestone_remaining -= size
            elif not self._remaining:
                return
            elif size >= self._remaining:
                text = "\n[trace] Live output limit reached. See logs/ in the artifact directory.\n"
                self._remaining = 0
            else:
                self._remaining -= size
        if encoding := getattr(stream, "encoding", None):
            text = text.encode(encoding, errors="replace").decode(encoding)
        try:
            print(text, end="", file=stream, flush=True)
        except OSError:
            pass

_DISPLAY: ContextVar[TraceDisplay | None] = ContextVar("bugfix_trace_display", default=None)


@contextmanager
def trace_output(mode: TraceMode | None = None, *, nexas: bool = False) -> Iterator[TraceDisplay]:
    """Route progress for one entry-point call, including its LangGraph worker context."""
    display = TraceDisplay(mode or _env_mode(), stderr=not nexas, nexas=nexas)
    token = _DISPLAY.set(display)
    try:
        yield display
    finally:
        _DISPLAY.reset(token)


def _short(text: Any, limit: int) -> str:
    value = str(text or "").replace("\n", "⏎")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _usage_totals(usage: Any) -> dict[str, int]:
    """``ResultMessage.usage`` → 归一化的 token 计数。

    兼容网关把 ``AssistantMessage.usage`` 全填 0，会话级用量只在
    ``ResultMessage`` 上，而且字段名各网关不一致（``input_tokens`` /
    ``prompt_tokens``）。这里把见过的写法都收一遍。
    """
    if not isinstance(usage, dict):
        return {}
    inner = usage.get("cache_creation")
    cache_1h = _int(usage.get("claude_cache_creation_1_h_tokens"))
    cache_5m = _int(usage.get("claude_cache_creation_5_m_tokens"))
    if isinstance(inner, dict):
        cache_1h = cache_1h or _int(inner.get("ephemeral_1h_input_tokens"))
        cache_5m = cache_5m or _int(inner.get("ephemeral_5m_input_tokens"))
    totals = {
        "input": _int(usage.get("input_tokens")) or _int(usage.get("prompt_tokens")),
        "output": _int(usage.get("output_tokens")) or _int(usage.get("completion_tokens")),
        "cache_read": _int(usage.get("cache_read_input_tokens")),
        "cache_write": _int(usage.get("cache_creation_input_tokens")) or (cache_1h + cache_5m),
    }
    return {k: v for k, v in totals.items() if v}


def format_usage(usage: Any, cost: Any = None) -> str:
    """``tok in=90.9k out=23.7k cache=693.8k cost=$1.43`` —— 一行说明这次花了多少。"""
    totals = _usage_totals(usage)
    return _format_totals(totals, cost)


def _format_totals(totals: dict[str, int], cost: Any = None) -> str:
    bits: list[str] = []
    if totals:
        def k(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

        bits.append(f"tok in={k(totals.get('input', 0))} out={k(totals.get('output', 0))}")
        if totals.get("cache_read"):
            bits.append(f"cache_read={k(totals['cache_read'])}")
        if totals.get("cache_write"):
            bits.append(f"cache_write={k(totals['cache_write'])}")
    if isinstance(cost, (int, float)) and cost:
        bits.append(f"cost=${cost:.2f}")
    return " ".join(bits)


class TraceRecorder:
    """一次 SDK 会话的轨迹。

    Parameters
    ----------
    log_dir:
        日志目录（通常是 ``artifact_dir/logs``）。为 ``None`` 时只显示实时进度。
    name:
        日志文件名主干，形如 ``agent3-BGCM2026102708222``。
    tag:
        实时进度的前缀，用来区分不同 Agent（如 ``[agent2]``）。
    """

    def __init__(
        self,
        log_dir: Optional[Path | str],
        name: str,
        *,
        tag: str = "",
    ) -> None:
        self._display = _DISPLAY.get() or TraceDisplay(_env_mode())
        self.enabled = self._display.mode != "off"
        self.detailed = self._display.mode == "detailed"
        self.tag = tag
        self._fh = None
        self._turn = 0
        self._turn_thinking = 0
        self._turn_tools: list[str] = []
        self._phase = "initial"
        self._has_text = False
        self._tools: dict[str, str] = {}
        self._partials: dict[tuple[str | None, int], list[str]] = {}
        self._partial_kinds: dict[tuple[str | None, int], str] = {}
        self._live_block: tuple[str | None, int] | None = None
        self._live_chars = 0
        self._closed = False
        # 累计用量：一个 recorder 可能跑多段（analysis + salvage + repair），
        # 每段结束都有 ResultMessage，这里累加，close() 时打一行总计。
        self._usage: dict[str, int] = {}
        self._cost = 0.0
        self._sessions = 0
        # SDK 的 num_turns 数的是 API 往返次数；self._turn 数的是消息条数
        # （一条 AssistantMessage 只带一个块），两者差一倍，对外只报前者。
        self._sdk_turns = 0

        if not self.enabled or log_dir is None:
            return
        try:
            root = Path(log_dir)
            root.mkdir(parents=True, exist_ok=True)
            self._fh = (root / f"{name}.jsonl").open("a", encoding="utf-8")
        except OSError as err:
            # 日志写不了不能影响主流程，降级成只打 stdout。
            print(f"[trace] cannot open log file: {err}", file=sys.stderr, flush=True)
            self._fh = None

    # -- 对外 ---------------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.detailed:
            self._end_text()
        else:
            self._finish_turn()
        self._report_totals()
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    def _report_totals(self) -> None:
        """会话总量：一次 recorder 可能跑 analysis + salvage + repair 多段。"""
        if not self._sessions:
            return
        if not self._usage and not self._cost:
            return
        summary = _format_totals(self._usage, self._cost)
        if not summary:
            return
        label = f"{self._sessions} 段" if self._sessions > 1 else "会话"
        self._live(f"[{label}] {summary} · turns={self._sdk_turns}", milestone=True)

    def sdk_options(self, options_type: Any) -> dict[str, bool]:
        """Use live deltas when the installed SDK accepts the option."""
        if not self.detailed:
            return {}
        try:
            params = signature(options_type).parameters
        except (TypeError, ValueError):
            return {}
        if "include_partial_messages" in params or any(p.kind == Parameter.VAR_KEYWORD for p in params.values()):
            return {"include_partial_messages": True}
        return {}

    def begin(self, phase: str, prompt: str, *, tickets: list[str]) -> None:
        if not self.detailed:
            return
        self._phase = phase
        self._has_text = False
        self._partials.clear()
        self._tools.clear()
        self._write("request", prompt=prompt, tickets=tickets)
        self._live(f"{phase} [{', '.join(tickets)}]", milestone=True)

    def error(self, error: Exception) -> None:
        if self.detailed:
            self._write("error", text=str(error))
            self._live(f"SDK error · {_short(str(error), 240)}", milestone=True)

    def message(self, message: Any) -> None:
        """记录一条 SDK 消息。

        迭代顺序很关键：``AssistantMessage`` 代表"新的一轮开始"，必须**先**收掉
        上一轮摘要、再递增轮次，最后才展开它的 content 块 —— 否则第一轮的
        思考/工具会被算到第 0 轮。
        """
        if not self.enabled or self._closed:
            return
        name = type(message).__name__
        parent = getattr(message, "parent_tool_use_id", None)
        if name == "StreamEvent":
            if self.detailed:
                self._stream_text(message.event, parent)
            return
        blocks = getattr(message, "content", None)
        block_list = blocks if isinstance(blocks, list) else []
        if name == "AssistantMessage":
            if not self.detailed:
                self._finish_turn()
            self._turn += 1
        elif self.detailed and name == "UserMessage" and isinstance(blocks, str):
            self._write("user", text=blocks)
        for block in block_list:
            self._node(block, parent)
        if name in ("ResultMessage", "SystemMessage"):
            self._node(message, parent)

    # -- 内部 ---------------------------------------------------------------

    def _emit(self, text: str) -> None:
        self._display.write(f"{self.tag + ' ' if self.tag else ''}{text[:_SUMMARY_LINE_MAX]}\n")

    def _write(self, kind: str, **fields: Any) -> None:
        if self._fh is None:
            return
        record = {"t": time.strftime("%H:%M:%S"), "kind": kind, **fields}
        if self.detailed:
            record["phase"] = self._phase
        try:
            self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except (OSError, TypeError, ValueError):
            pass

    def _live(self, text: str, *, milestone: bool = False) -> None:
        self._end_text()
        self._display.write(f"{self.tag + ' ' if self.tag else ''}{text}\n", milestone=milestone)

    def _end_text(self) -> None:
        if self._live_block is not None:
            self._display.write("\n")
            self._live_block = None

    def _stream_text(self, event: dict[str, Any], parent: str | None) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self._partials = {key: chunks for key, chunks in self._partials.items() if key[0] != parent}
            self._partial_kinds = {key: k for key, k in self._partial_kinds.items() if key[0] != parent}
            self._end_text()
            return
        index = event.get("index")
        if not isinstance(index, int):
            return
        key = (parent, index)
        if kind == "content_block_stop" and self._live_block == key:
            self._end_text()
            return
        block = event.get("delta") or event.get("content_block") or {}
        block_type = block.get("type")
        if kind not in ("content_block_start", "content_block_delta"):
            return
        # 网关把思考走 thinking_delta，正文走 text_delta。二者都要收，
        # 否则 detailed 模式比 summary 模式丢的信息更多。
        if block_type in ("thinking", "thinking_delta"):
            field, record_kind, partial_kind = "thinking", "thinking_delta", "thinking"
        elif block_type in ("text", "text_delta"):
            field, record_kind, partial_kind = "text", "text_delta", "text"
        else:
            return
        text = block.get(field)
        if not isinstance(text, str) or not text:
            return
        self._partials.setdefault(key, []).append(text)
        self._partial_kinds[key] = partial_kind
        self._write(record_kind, index=index, parentToolUseId=parent, text=text)
        # 思考正文只落盘，不进实时输出：它是最长的一类内容，会把宿主
        # 64 KB 的 stdout 预算一次吃光，而实时流要留给工具事件和结论。
        if partial_kind == "thinking":
            return
        self._has_text = True
        if self._live_block != key:
            self._end_text()
            self._live_block = key
            self._live_chars = 0
            if self.tag:
                self._display.write(self.tag + " ")
        if self._display.nexas:
            remaining = _NEXAS_TEXT_CHARS - self._live_chars
            if remaining <= 0:
                return
            if len(text) > remaining:
                text = text[:remaining] + "…"
        self._live_chars += len(text)
        self._display.write(text)

    def _visible_text(self, text: str, parent: str | None) -> None:
        # The SDK follows deltas with a completed block. Print any suffix once.
        for key, chunks in self._partials.items():
            if key[0] != parent or self._partial_kinds.get(key) == "thinking":
                continue
            streamed = "".join(chunks)
            if text.startswith(streamed):
                del self._partials[key]
                text = text[len(streamed):]
                break
        if text:
            if self._display.nexas:
                text = _short(text, _NEXAS_TEXT_CHARS)
            self._live(text)

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

    def _node(self, block: Any, parent: str | None) -> None:
        name = type(block).__name__

        if name == "ThinkingBlock":
            text = getattr(block, "thinking", "") or ""
            # detailed 模式下正文只落盘（思考很长，交给 64 KB 的 stdout 会挤掉工具事件）。
            self._write("thinking", turn=self._turn, text=text if self.detailed else _short(text, _TEXT_PREVIEW))
            if not self.detailed:
                self._turn_thinking += len(text)
            return

        if name == "TextBlock":
            text = getattr(block, "text", "") or ""
            self._write("text", turn=self._turn, text=text if self.detailed else _short(text, _TEXT_PREVIEW))
            if self.detailed:
                self._has_text |= bool(text)
                self._visible_text(text, parent)
            return

        if name == "ToolUseBlock":
            tool = str(getattr(block, "name", "") or "?")
            params = getattr(block, "input", {}) or {}
            tool_id = str(getattr(block, "id", ""))
            self._write("tool_use", turn=self._turn, name=tool, input=params, toolUseId=tool_id)
            if self.detailed:
                self._tools[tool_id] = tool
                label = next((params[key] for key in ("file_path", "path", "pattern", "description")
                              if isinstance(params.get(key), str) and params[key]), "")
                self._live(f"→ {tool}" + (f" · {_short(label, 240)}" if label else ""))
            else:
                self._turn_tools.append(tool)
            return

        if name == "ToolResultBlock":
            content = getattr(block, "content", None)
            text = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False, default=str
            ) if content is not None else ""
            tool_id = str(getattr(block, "tool_use_id", ""))
            ok = not bool(getattr(block, "is_error", False))
            fields = {"content": content, "toolUseId": tool_id} if self.detailed else {"preview": _short(text, _TOOL_RESULT_PREVIEW)}
            self._write("tool_result", turn=self._turn, ok=ok, bytes=len(text or ""), **fields)
            if self.detailed:
                tool = self._tools.pop(tool_id, "Tool")
                limit = 160 if self._display.nexas else 500
                self._live(f"← {tool} · {'ok' if ok else 'error'}" + (f" · {_short(text, limit)}" if text else ""))
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
            result_text = getattr(block, "result", None)
            structured = getattr(block, "structured_output", None)
            usage = getattr(block, "usage", None)
            cost = getattr(block, "total_cost_usd", None)
            turns = getattr(block, "num_turns", None)
            totals = _usage_totals(usage)
            self._sessions += 1
            if isinstance(turns, int) and turns > 0:
                self._sdk_turns += turns
            for key, value in totals.items():
                self._usage[key] = self._usage.get(key, 0) + value
            if isinstance(cost, (int, float)):
                self._cost += cost
            fields = {
                "text": result_text, "structuredOutput": structured,
                "sessionId": getattr(block, "session_id", None),
                "errors": getattr(block, "errors", None),
                "terminalReason": getattr(block, "terminal_reason", None),
            } if self.detailed else {}
            self._write(
                "result",
                subtype=getattr(block, "subtype", None),
                is_error=bool(getattr(block, "is_error", False)),
                cost=cost,
                turns=turns,
                # AssistantMessage.usage 在兼容网关上恒为 0；会话级用量只有
                # ResultMessage 带（实测 input/output token 都在这里）。
                usage=usage,
                modelUsage=getattr(block, "model_usage", None),
                **fields,
            )
            if self.detailed:
                if not self._has_text and structured is None and isinstance(result_text, str) and result_text:
                    self._visible_text(result_text, parent)
                status = getattr(block, "terminal_reason", None) or getattr(block, "subtype", None)
                status = status or ("error" if getattr(block, "is_error", False) else "completed")
                summary = format_usage(usage, cost)
                self._live(f"SDK result · {status}" + (f" · {summary}" if summary else ""), milestone=True)
            return


def open_recorder(
    artifact_dir: Optional[str | Path],
    name: str,
    *,
    tag: str = "",
) -> TraceRecorder:
    """按 ``artifact_dir/logs/`` 开一个记录器。

    ``artifact_dir`` 为空时仍可显示实时进度。
    """
    log_dir = (Path(artifact_dir) / "logs") if artifact_dir else None
    return TraceRecorder(log_dir, name, tag=tag)
