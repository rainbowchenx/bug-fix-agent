"""T1：SDK 原始响应在 parse 之前保全；失败不得标已保存。"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from bugfix_platform.agents.cartographer.investigation_store import (
    DEFAULT_TRANSCRIPT_LIMIT,
    InvestigationRecorder,
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


def test_recorder_keeps_structured_and_candidates(tmp_path: Path):
    recorder = InvestigationRecorder(tmp_path, "g1", "call-1")
    envelope = _envelope()
    recorder.save_response(envelope)
    recorder.save_parse_inputs(envelope["parse_candidates"])
    recorder.finalize(status="saved", stop_reason="completed")
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
    InvestigationRecorder(tmp_path, "g1", "call-1").save_response(_envelope())
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
        InvestigationRecorder(tmp_path, "g1", "call-x")
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


@pytest.mark.parametrize("write_stage", ["__init__", "append_event", "save_response", "finalize", "progress"])
def test_artifact_write_failure_keeps_results_without_complete_cache(tmp_path, monkeypatch, write_stage):
    from claude_agent_sdk.types import ResultMessage
    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request

    work = tmp_path / "repo"
    work.mkdir()
    source = b"def example(): pass\n"
    (work / "a.py").write_bytes(source)
    payload = {"partial": False, "defectCodeMatches": [{"defectId": "0", "facts": [{
        "claim": "a.py defines example",
        "reference": {"repoId": ".", "path": "a.py", "snippet": "def example()",
                      "contentDigest": sha256(source).hexdigest()},
    }]}]}
    _install_query(monkeypatch, [ResultMessage(
        subtype="success", duration_ms=3, duration_api_ms=3, is_error=False,
        num_turns=1, session_id="offline", structured_output=payload,
    )])

    def fail_write(*args, **kwargs):
        raise OSError("simulated write failure")

    artifacts, cache = tmp_path / "artifacts", tmp_path / "cache"
    with monkeypatch.context() as fault:
        if write_stage == "progress":
            fault.setattr("bugfix_platform.agents.cartographer.investigation.save_group_progress", fail_write)
        else:
            fault.setattr(InvestigationRecorder, write_stage, fail_write)
        result = investigate_groups(request(work, 1), run_claude_cartography,
                                    artifact_dir=artifacts, cache_dir=cache)

    match, = result.knowledge.defectCodeMatches
    assert match.facts[0].validity == "reference_verified"
    assert result.knowledge.partial
    assert not list(cache.glob("*.json"))
    assert result.knowledge.investigationRuns[0]["stopReason"] == "artifact_error"
    if write_stage == "progress":
        assert match.storageStatus == "saved"
        assert "progress write failed" in result.detail
    else:
        assert match.storageStatus == "artifact_error"
        assert match.investigationStatus == "partial"
        assert not list((artifacts / "agent2" / "groups").rglob("latest.json"))
        progress = json.loads((artifacts / "agent2" / "progress.json").read_text(encoding="utf-8"))
        assert progress["stopReason"] == progress["groups"][0]["stopReason"] == "artifact_error"

    recovered = investigate_groups(request(work, 1), run_claude_cartography,
                                    artifact_dir=artifacts, resume_dir=artifacts, cache_dir=cache)
    assert recovered.knowledge.defectCodeMatches[0].storageStatus == "saved"
    assert not recovered.knowledge.partial
    assert len(list(cache.glob("*.json"))) == 1


def test_invalid_candidate_does_not_discard_other_investigation_fields(tmp_path, monkeypatch):
    from claude_agent_sdk.types import ResultMessage
    from tests.platform.test_investigation_batches import request

    work = tmp_path / "repo"
    work.mkdir()
    _install_query(monkeypatch, [ResultMessage(
        subtype="success", duration_ms=3, duration_api_ms=3, is_error=False,
        num_turns=1, session_id="offline", structured_output={"defectCodeMatches": [{
            "defectId": "0", "candidates": [{"path": "absent.py", "source": "grep", "why": "name"}],
            "hypotheses": ["Check defaults"], "ruledOut": ["Route was checked"],
            "openQuestions": ["Which option is set?"], "nextChecks": ["Read the caller"],
        }]},
    )])

    match, = run_claude_cartography(request(work, 1)).knowledge.defectCodeMatches
    assert not match.candidates
    assert match.hypotheses == ["Check defaults"]
    assert match.ruledOut == ["Route was checked"]
    assert match.openQuestions == ["Which option is set?"]
    assert match.nextChecks == ["Read the caller"]
    assert match.investigationStatus == "partial"


def test_sdk_format_repair_preserves_initial_response(tmp_path, monkeypatch):
    from dataclasses import replace
    import claude_agent_sdk
    from claude_agent_sdk.types import ResultMessage
    from tests.platform.test_investigation_batches import request

    work = tmp_path / "repo"
    work.mkdir()
    calls = []

    async def query(*, prompt, options):
        calls.append(options.resume)
        repairing = bool(options.resume)
        yield ResultMessage(
            subtype="success" if repairing else "error_max_turns",
            duration_ms=3, duration_api_ms=3, is_error=not repairing,
            num_turns=1, session_id="offline", result='{"defectCodeMatches": []}' if repairing else "unfinished",
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    req = replace(request(work, 1), artifact_dir=tmp_path / "out", max_turns=4, group_id="g1", call_id="c1")
    run_claude_cartography(req)

    assert calls == [None, "offline"]
    attempt = req.artifact_dir / "agent2" / "groups" / "g1" / "attempts" / "c1"
    initial = json.loads((attempt / "response.json").read_text(encoding="utf-8"))
    repaired = json.loads((attempt / "repair-response.json").read_text(encoding="utf-8"))
    assert initial["result_text"] == "unfinished"
    assert repaired["result_text"] == '{"defectCodeMatches": []}'


def test_sdk_success_repairs_only_missing_or_ambiguous_tickets(tmp_path, monkeypatch):
    import claude_agent_sdk
    from claude_agent_sdk.types import ResultMessage

    from bugfix_platform.agents.cartographer.investigation import investigate_groups
    from tests.platform.test_investigation_batches import request

    work = tmp_path / "repo"
    work.mkdir()
    source = b"def example(): pass\n"
    (work / "a.py").write_bytes(source)

    def fact(claim):
        return {"claim": claim, "reference": {"repoId": ".", "path": "a.py",
                "snippet": "def example()", "contentDigest": sha256(source).hexdigest()}}

    initial = {
        "partial": False, "unexpected": False,
        "defectCodeMatches": [
            {"defectId": "0", "facts": [False, fact("keep original")], "confidence": {}, "hypotheses": True,
             "searchedScopes": [False, "src/"],
             "candidates": [{"path": "a.py", "source": "invented"}, {"path": "absent.py", "source": "grep"}]},
            {"defectId": "2", "facts": ["first ambiguous"]},
            {"defectId": "2", "facts": ["second ambiguous"]},
        ],
    }
    repaired = {"defectCodeMatches": [
        {"defectId": "0", "facts": [fact("must not overwrite")]},
        {"defectId": "1", "facts": [fact("missing now found")]},
        {"defectId": "2", "facts": [fact("identity now clear")]},
    ]}
    calls = []

    async def query(*, prompt, options):
        calls.append((prompt, options.resume, options.max_turns))
        yield ResultMessage(
            subtype="success", duration_ms=3, duration_api_ms=3, is_error=False,
            num_turns=1 if options.resume else 3, session_id="offline",
            result="note {} and " + json.dumps(repaired) if options.resume else None,
            structured_output=None if options.resume else initial,
            total_cost_usd=0.01,
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    artifacts = tmp_path / "out"
    result = investigate_groups(request(work, 3), run_claude_cartography, artifact_dir=artifacts)
    matches = {match.defectId: match for match in result.knowledge.defectCodeMatches}
    assert len(calls) == 2
    assert calls[1][1:] == ("offline", 2)
    assert calls[1][0].endswith('["1", "2"]')
    assert [matches[i].facts[0].claim for i in "012"] == ["keep original", "missing now found", "identity now clear"]
    assert matches["0"].searchedScopes == ["src/"]
    assert not result.knowledge.partial
    assert result.knowledge.investigationProgress["counts"] == {
        "planned": 3, "launched": 3, "accepted": 3, "pending": 0, "running": 0,
        "interrupted": 0, "complete": 3, "partial": 0, "failed": 0,
    }

    parse_path, = artifacts.rglob("parse-result.json")
    parse = json.loads(parse_path.read_text(encoding="utf-8"))
    assert parse["repair"]["requestedIds"] == ["1", "2"]
    assert parse["fieldRefs"]["0"]["facts"] == "response.json#structured_output.defectCodeMatches[0].facts"
    assert parse["fieldRefs"]["1"]["facts"] == (
        "repair-response.json#parse_candidates[0].objects[1].defectCodeMatches[1].facts"
    )
    issues = {item["rawRef"]: item["reason"] for item in parse["issues"]}
    assert issues["response.json#structured_output.defectCodeMatches[0].facts[0]"] == "bad_fact_element"
    assert issues["response.json#structured_output.defectCodeMatches[0].candidates[0].source"] == "illegal_source"
    assert issues["response.json#structured_output.defectCodeMatches[0].candidates[1]"] == "missing"
    assert issues["response.json#structured_output.defectCodeMatches[1].defectId"] == "duplicate_ticket"
    assert issues["response.json#structured_output.defectCodeMatches[2].defectId"] == "duplicate_ticket"
    assert issues["response.json#structured_output.unexpected"] == "unknown_field"
    for raw_ref in parse["responses"].values():
        source_path = parse_path.parent / raw_ref["path"]
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        assert digest == raw_ref["digest"]
        assert payload["cost"] == 0.01
    progress = json.loads((artifacts / "agent2" / "progress.json").read_text(encoding="utf-8"))
    assert progress["billing"]["aggregate"] == "unknown"


@pytest.mark.parametrize("limit", ["turns", "deadline", "cost", "no_session", "one_retry"])
def test_missing_tickets_never_trigger_unbounded_followup(tmp_path, monkeypatch, limit):
    from dataclasses import replace
    import time
    import claude_agent_sdk
    from claude_agent_sdk.types import ResultMessage

    from tests.platform.test_investigation_batches import request

    calls = []

    async def query(*, prompt, options):
        calls.append(options.resume)
        yield ResultMessage(
            subtype="error_max_budget_usd" if limit == "cost" else "success",
            is_error=limit == "cost", duration_ms=3, duration_api_ms=3,
            num_turns=4 if limit == "turns" else 1,
            session_id="" if limit == "no_session" else "offline",
            structured_output={"partial": False, "defectCodeMatches": [
                {"defectId": "0", "facts": ["retain the only observation"]},
            ]},
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    work = tmp_path / "repo"
    work.mkdir()
    req = replace(request(work, 2), max_turns=4, artifact_dir=tmp_path / "out",
                  deadline=time.monotonic() - 1 if limit == "deadline" else None)
    result = run_claude_cartography(req)
    assert calls == ([None, "offline"] if limit == "one_retry" else [None])
    assert result.knowledge.partial
    assert result.knowledge.defectCodeMatches[0].facts[0].claim == "retain the only observation"
    assert result.knowledge.defectCodeMatches[1].investigationStatus == "failed"
    assert result.stop_reason == "output_invalid"
