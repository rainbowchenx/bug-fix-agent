"""T1：SDK 原始响应在 parse 之前保全；失败不得标已保存。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bugfix_contracts.code_knowledge import RawResponseRef
from bugfix_platform.agents.cartographer.investigation_store import (
    DEFAULT_TRANSCRIPT_LIMIT,
    InvestigationRecorder,
    record_group_response,
    save_format_repair,
)
from bugfix_platform.sdk.cartography import CartographyRequest
from bugfix_platform.agents.cartographer.handoff import run_claude_cartography


def _envelope(**kw: Any) -> dict[str, Any]:
    payload = {
        "structured_output": {"defectCodeMatches": [{"defectId": "D1", "facts": ["s"]}]},
        "result_text": '{"defectCodeMatches":[{"defectId":"D1"}]}',
        "errors": [],
        "parse_candidates": [
            '{"defectCodeMatches":[{"defectId":"D1"}]}',
            "```json\n{\"partial\": true}\n```",
        ],
    }
    payload.update(kw)
    return payload


def test_record_group_response_keeps_structured_and_candidates(tmp_path: Path):
    ref = record_group_response(tmp_path, "g1", "call-1", _envelope())
    assert isinstance(ref, RawResponseRef)
    dest = tmp_path / "agent2" / "groups" / "g1" / "attempts" / "call-1"
    response = json.loads((dest / "response.json").read_text(encoding="utf-8"))
    assert response["structured_output"]["defectCodeMatches"][0]["defectId"] == "D1"
    assert len(response["parse_candidates"]) == 2
    assert (dest / "parse-candidates.json").is_file()
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["callId"] == "call-1"
    latest = json.loads((tmp_path / "agent2" / "groups" / "g1" / "latest.json").read_text(encoding="utf-8"))
    assert latest["callId"] == "call-1"


def test_format_repair_does_not_overwrite_initial_response(tmp_path: Path):
    record_group_response(tmp_path, "g1", "call-1", _envelope())
    save_format_repair(
        tmp_path,
        "g1",
        "call-1",
        before='{"broken":',
        after='{"defectCodeMatches":[]}',
    )
    dest = tmp_path / "agent2" / "groups" / "g1" / "attempts" / "call-1"
    initial = json.loads((dest / "response.json").read_text(encoding="utf-8"))
    repair = json.loads((dest / "format-repair.json").read_text(encoding="utf-8"))
    assert "parse_candidates" in initial
    assert repair["before"] == '{"broken":'
    assert repair["after"].startswith("{")
    assert initial.get("after") is None


def test_stream_events_survive_later_exception(tmp_path: Path):
    rec = InvestigationRecorder(tmp_path, "g1", "call-stream")
    rec.append_event({"kind": "assistant", "text": "looking at src/a.ts"})
    rec.append_event({"kind": "tool_result", "name": "Read", "content": "export const a = 1"})
    rec.append_event({"kind": "error", "text": "stream closed"})
    transcript = (rec.attempt_dir / "transcript.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in transcript.splitlines() if line.strip()]
    assert lines[0]["text"] == "looking at src/a.ts"
    assert lines[1]["name"] == "Read"
    assert lines[2]["kind"] == "error"
    parse = json.loads((rec.attempt_dir / "parse-result.json").read_text(encoding="utf-8"))
    assert parse["status"] != "saved_complete"


def test_unwritable_root_is_artifact_error_not_cached(tmp_path: Path):
    blocker = tmp_path / "agent2"
    blocker.write_text("file not dir", encoding="utf-8")
    with pytest.raises(OSError):
        record_group_response(tmp_path, "g1", "call-x", _envelope())
    assert not (tmp_path / "agent2" / "groups" / "g1" / "latest.json").exists()


def test_secret_env_not_echoed_in_manifest(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    rec = InvestigationRecorder(
        tmp_path,
        "g1",
        "call-1",
        input_digest="ab" * 32,
        budget={"max_turns": 8},
    )
    rec.finalize(status="saved", stop_reason="completed")
    text = (rec.attempt_dir / "manifest.json").read_text(encoding="utf-8")
    assert "sk-secret-value" not in text
    assert "ANTHROPIC_API_KEY" not in text


def test_transcript_truncation_keeps_parse_input(tmp_path: Path):
    rec = InvestigationRecorder(tmp_path, "g1", "call-big", transcript_limit=64)
    rec.append_event({"kind": "assistant", "text": "x" * 200})
    rec.save_parse_inputs(["COMPLETE-JSON-CANDIDATE"])
    rec.finalize(status="saved", stop_reason="completed", truncated=True)
    manifest = json.loads((rec.attempt_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["transcriptTruncated"] is True
    assert manifest["status"] == "saved"
    candidates = json.loads((rec.attempt_dir / "parse-candidates.json").read_text(encoding="utf-8"))
    assert "COMPLETE-JSON-CANDIDATE" in candidates


def _install_query(monkeypatch, messages, *, explode: Exception | None = None):
    import claude_agent_sdk

    async def fake_query(*, prompt: str, options: Any):
        for message in messages:
            yield message
        if explode is not None:
            raise explode

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_run_claude_cartography_records_before_parse(tmp_path: Path, monkeypatch):
    from claude_agent_sdk.types import ResultMessage
    from bugfix_contracts import DefectBatch, validate_code_knowledge
    from tests.helpers import ensure_git_repo

    work = ensure_git_repo(tmp_path / "repo")
    payload = {"defectCodeMatches": [{"defectId": "D1", "searchedScopes": ["src/"]}]}
    msg = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=2,
        session_id="s-rec",
        result=json.dumps(payload),
        structured_output=payload,
        total_cost_usd=0.01,
        terminal_reason="completed",
    )
    _install_query(monkeypatch, [msg])
    artifacts = tmp_path / "artifacts"
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "p",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "x",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "intent": "logic",
                }
            ],
        }
    )
    baseline = validate_code_knowledge(
        {
            "schemaVersion": "0.4.0",
            "productLine": "p",
            "workDir": str(work),
            "generatedAt": "2026-01-01T00:00:00Z",
            "defectCodeMatches": [{"defectId": "D1"}],
        }
    )
    result = run_claude_cartography(
        CartographyRequest(
            work_dir=str(work),
            defect_batch=batch,
            baseline=baseline,
            artifact_dir=artifacts,
            group_id="g1",
            call_id="call-sdk",
        )
    )
    assert result.source == "sdk"
    saved = artifacts / "agent2" / "groups" / "g1" / "attempts" / "call-sdk" / "response.json"
    assert saved.is_file()
    body = json.loads(saved.read_text(encoding="utf-8"))
    assert body["structured_output"]["defectCodeMatches"][0]["defectId"] == "D1"


def test_run_claude_cartography_keeps_stream_on_error(tmp_path: Path, monkeypatch):
    from tests.helpers import ensure_git_repo
    from bugfix_contracts import DefectBatch, validate_code_knowledge

    class Mid:
        content = [type("T", (), {"text": "partial observation about src/foo.ts"})()]
        result = None

    work = ensure_git_repo(tmp_path / "repo")
    _install_query(monkeypatch, [Mid()], explode=RuntimeError("socket closed"))
    artifacts = tmp_path / "artifacts"
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.4.0",
            "productLine": "p",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "x",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "intent": "logic",
                }
            ],
        }
    )
    baseline = validate_code_knowledge(
        {
            "schemaVersion": "0.4.0",
            "productLine": "p",
            "workDir": str(work),
            "generatedAt": "2026-01-01T00:00:00Z",
            "defectCodeMatches": [{"defectId": "D1"}],
        }
    )
    run_claude_cartography(
        CartographyRequest(
            work_dir=str(work),
            defect_batch=batch,
            baseline=baseline,
            artifact_dir=artifacts,
            group_id="g-err",
            call_id="call-err",
        )
    )
    transcript = (
        artifacts / "agent2" / "groups" / "g-err" / "attempts" / "call-err" / "transcript.jsonl"
    )
    assert "src/foo.ts" in transcript.read_text(encoding="utf-8")
    parse = json.loads(
        (artifacts / "agent2" / "groups" / "g-err" / "attempts" / "call-err" / "parse-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert parse["status"] in {"artifact_error", "sdk_error", "incomplete"}
    assert not (artifacts / "agent2" / "groups" / "g-err" / "latest.json").exists() or (
        json.loads((artifacts / "agent2" / "groups" / "g-err" / "latest.json").read_text(encoding="utf-8")).get(
            "status"
        )
        != "saved"
    )


def test_default_transcript_limit_is_32mib():
    assert DEFAULT_TRANSCRIPT_LIMIT == 32 * 1024 * 1024
