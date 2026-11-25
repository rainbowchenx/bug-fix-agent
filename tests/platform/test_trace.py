"""SDK 轨迹记录：全量落盘 + stdout 摘要。

模型做了什么是排查的关键 —— 以前 ``_drive()`` 只挑出纯文本和 ResultMessage，
ThinkingBlock / ToolUseBlock / ToolResultBlock 全部丢弃，出问题只能看到最后
一行汇总。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from bugfix_platform.sdk.trace import TraceRecorder, trace_enabled


def _result(**kw) -> ResultMessage:
    base = dict(
        subtype="success", is_error=False, total_cost_usd=0.1, num_turns=1,
        duration_ms=1, duration_api_ms=1, session_id="s1", result=None,
    )
    base.update(kw)
    return ResultMessage(**base)


@pytest.fixture(autouse=True)
def _trace_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUGFIX_TRACE", raising=False)  # 默认开


def _lines(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


def test_writes_thinking_and_tool_use(tmp_path, capsys):
    rec = TraceRecorder(tmp_path, "demo", tag="[t]")
    rec.message(AssistantMessage(
        content=[ThinkingBlock(thinking="先看入口文件", signature="sig")], model="m"
    ))
    rec.message(AssistantMessage(
        content=[ToolUseBlock(id="1", name="Read", input={"file_path": "a.vue"})], model="m"
    ))
    rec.close()

    records = _lines(tmp_path / "demo.jsonl")
    kinds = [r["kind"] for r in records]
    assert "thinking" in kinds
    assert "tool_use" in kinds

    thinking = next(r for r in records if r["kind"] == "thinking")
    assert thinking["text"] == "先看入口文件"
    assert thinking["turn"] == 1

    tool = next(r for r in records if r["kind"] == "tool_use")
    assert tool["name"] == "Read"
    assert tool["input"] == {"file_path": "a.vue"}


def test_summary_prints_once_per_turn_without_tool_args(tmp_path, capsys):
    """摘要只放轮次/字数/工具名，不放工具参数 —— stdout 总共才 64 KB。"""
    rec = TraceRecorder(tmp_path, "demo", tag="[t]")
    rec.message(AssistantMessage(
        content=[
            ThinkingBlock(thinking="x" * 10, signature="s"),
            ToolUseBlock(id="1", name="Read", input={"file_path": "secret/a.vue"}),
            ToolUseBlock(id="2", name="Read", input={"file_path": "secret/b.vue"}),
            ToolUseBlock(id="3", name="Grep", input={"pattern": "foo"}),
        ],
        model="m",
    ))
    rec.close()

    out = capsys.readouterr().out
    assert "turn 1" in out
    assert "think=10c" in out
    # 同名工具聚合成 ×N
    assert "Read×2" in out
    assert "Grep" in out
    # 不含具体路径
    assert "secret/a.vue" not in out


def test_result_does_not_duplicate_summary(tmp_path, capsys):
    rec = TraceRecorder(tmp_path, "demo", tag="[t]")
    rec.message(AssistantMessage(content=[TextBlock(text="结论")], model="m"))
    rec.message(_result())
    rec.close()

    out = capsys.readouterr().out
    assert out.count("turn 1") == 1


def test_tool_result_recorded_with_preview(tmp_path):
    rec = TraceRecorder(tmp_path, "demo", tag="[t]")
    rec.message(AssistantMessage(
        content=[ToolResultBlock(
            tool_use_id="1", content="文件内容" * 1000, is_error=None
        )],
        model="m",
    ))
    rec.close()

    record = next(r for r in _lines(tmp_path / "demo.jsonl") if r["kind"] == "tool_result")
    assert record["ok"] is True
    assert record["bytes"] == len("文件内容" * 1000)
    # preview 要截断，不能把整个文件写进日志
    assert len(record["preview"]) < 4100


def test_disabled_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BUGFIX_TRACE", "0")
    rec = TraceRecorder(tmp_path, "demo")
    rec.message(AssistantMessage(content=[ThinkingBlock(thinking="x", signature="s")], model="m"))
    rec.close()

    assert not (tmp_path / "demo.jsonl").exists()
    assert capsys.readouterr().out == ""


def test_no_log_dir_still_echoes_summary(capsys):
    """artifact_dir 为空时不写文件，但 stdout 摘要照打（客户端靠它看进度）。"""
    rec = TraceRecorder(None, "demo", tag="[t]")
    rec.message(AssistantMessage(content=[TextBlock(text="hi")], model="m"))
    rec.close()

    assert "turn 1" in capsys.readouterr().out


def test_unwritable_dir_degrades_without_raising(tmp_path):
    """日志写不了不能影响主流程。"""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("占用", encoding="utf-8")

    rec = TraceRecorder(blocker / "logs", "demo", tag="[t]")  # 父路径是文件
    rec.message(AssistantMessage(content=[TextBlock(text="hi")], model="m"))
    rec.close()  # 不该抛


@pytest.mark.parametrize(
    "value, expected",
    [(None, True), ("", True), ("1", True), ("0", False), ("false", False), ("OFF", False)],
)
def test_trace_enabled_default_on(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("BUGFIX_TRACE", raising=False)
    else:
        monkeypatch.setenv("BUGFIX_TRACE", value)
    assert trace_enabled() is expected


def test_noisy_thinking_tokens_dropped(tmp_path):
    """thinking_tokens 是逐 token 心跳，一个会话能刷近万条，必须过滤掉。"""
    from claude_agent_sdk import SystemMessage

    rec = TraceRecorder(tmp_path, "demo", tag="[t]")
    rec.message(SystemMessage(subtype="thinking_tokens", data={"estimated_tokens": 1}))
    rec.message(SystemMessage(subtype="init", data={"cwd": "E:/repo"}))
    rec.close()

    records = _lines(tmp_path / "demo.jsonl")
    assert all(r["kind"] != "system" or r["subtype"] != "thinking_tokens" for r in records)
    assert any(r["kind"] == "system" and r["subtype"] == "init" for r in records)
