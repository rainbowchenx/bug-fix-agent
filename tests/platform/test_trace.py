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
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from bugfix_platform.sdk.trace import TraceRecorder, trace_output


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
    recorder = TraceRecorder(None, "demo")
    assert recorder.enabled is expected
    recorder.close()


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


def test_detailed_trace_streams_text_once_and_records_full_results(tmp_path, capsys):
    file_contents = "源码内容\n" * 1500
    structured = {"rootCause": {"summary": "race in preview"}}

    with trace_output("detailed"):
        rec = TraceRecorder(tmp_path, "demo", tag="[agent3]")
        assert rec.sdk_options(ClaudeAgentOptions) == {"include_partial_messages": True}
        rec.begin("analysis", "Inspect the preview", tickets=["D1"])
        rec.message(StreamEvent(uuid="event", session_id="s1", event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Reading preview"},
        }))
        live = capsys.readouterr()
        assert "Reading preview" in live.err
        assert live.out == ""

        rec.message(AssistantMessage(content=[
            TextBlock(text="Reading preview now."),
            ThinkingBlock(thinking="internal", signature="s"),
            ToolUseBlock(id="r1", name="Read", input={"file_path": "src/preview.ts"}),
        ], model="m"))
        rec.message(UserMessage(content=[ToolResultBlock(
            tool_use_id="r1", content=file_contents, is_error=False,
        )]))
        rec.message(_result(structured_output=structured))
        assert rec._turn_tools == [] and rec._turn_thinking == 0
        rec.close()

    live = capsys.readouterr()
    assert live.out == ""
    assert " now." in live.err and "Reading preview" not in live.err
    assert "→ Read · src/preview.ts" in live.err and "← Read · ok" in live.err
    assert "internal" not in live.err
    events = _lines(tmp_path / "demo.jsonl")
    assert [event["kind"] for event in events] == [
        "request", "text_delta", "text", "tool_use", "tool_result", "result",
    ]
    assert events[0]["tickets"] == ["D1"]
    assert events[-2]["content"] == file_contents
    assert events[-1]["structuredOutput"] == structured


def test_nexas_display_budget_is_shared_and_does_not_limit_files(tmp_path, capsys):
    body = "文" * 10000
    with trace_output("detailed", nexas=True):
        for name in ("agent2-g1", "agent3-D1"):
            recorder = TraceRecorder(tmp_path, name)
            recorder.begin("analysis", "prompt", tickets=["D1"])
            for _ in range(10):
                recorder.message(AssistantMessage(content=[TextBlock(text=body)], model="m"))
            recorder.close()
        follow_up = TraceRecorder(tmp_path, "follow-up")
        follow_up.begin("analysis salvage", "repair prompt", tickets=["D1"])
        follow_up.close()

    live = capsys.readouterr()
    assert live.err == ""
    assert len(live.out.encode("utf-8")) < 64 * 1024
    assert live.out.count("Live output limit reached") == 1
    assert live.out.index("analysis salvage [D1]") > live.out.index("Live output limit reached")
    assert _lines(tmp_path / "agent3-D1.jsonl")[-1]["text"] == body
