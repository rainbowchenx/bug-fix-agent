"""T5：逐轮分析快照不可覆盖，latest 原子提交。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_contracts.analysis_report import TicketReport
from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, InputRevision
from bugfix_platform.agents.analyst.analysis_store import (
    SnapshotConflict,
    build_snapshot_from_entry,
    load_analysis_snapshot,
    save_analysis_snapshot,
    snapshot_digest,
)
from bugfix_platform.agents.analyst.run import run_analyst
from bugfix_platform.sdk.analyze import AnalyzeResult


def _entry(defect_id: str = "D1", summary: str = "first round") -> dict:
    return {
        "defectId": defect_id,
        "attemptId": "a1",
        "outcome": "plan_only",
        "proposedFix": {"summary": "change arg order", "steps": [], "targetFiles": ["src/add.py"]},
        "rootCause": {
            "summary": summary,
            "ruledOut": ["ui"],
            "openQuestions": [],
            "claims": [
                {
                    "claimId": "c1",
                    "statement": "add(a,b) swapped",
                    "role": "conclusion",
                    "status": "unverified",
                    "evidenceRefs": [],
                    "assumptions": [],
                }
            ],
            "questions": [
                {
                    "id": "q1",
                    "kind": "choice",
                    "reason": "which order is required?",
                    "relatedClaimIds": ["c1"],
                    "category": "product",
                }
            ],
        },
        "localization": {
            "candidates": [{"path": "src/add.py", "why": "add", "snippet": "return a-b"}],
        },
        "confidence": "medium",
        "verifyStatus": "skipped",
    }


def test_first_round_snapshot_keeps_full_record(tmp_path: Path):
    attempt = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D1",
        execution="completed",
        resolution="analysis_only",
    )
    snap = build_snapshot_from_entry(_entry(), revision=InputRevision(revisionId="D1:v0", defectId="D1"))
    ref = save_analysis_snapshot(tmp_path, attempt, snap)
    loaded = load_analysis_snapshot(tmp_path, "D1", "a1")
    assert loaded.digest == ref.digest
    assert loaded.ticketReport.rootCause.summary == "first round"
    assert loaded.ticketReport.rootCause.questions[0].id == "q1"
    assert (tmp_path / "defects" / "D1" / "feedback-form.md").is_file()


def test_second_round_does_not_overwrite_first(tmp_path: Path):
    a1 = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a1", defectId="D1", execution="completed", resolution="analysis_only")
    a2 = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a2", defectId="D1", execution="completed", resolution="analysis_only", parentAttemptId="a1")
    save_analysis_snapshot(tmp_path, a1, build_snapshot_from_entry(_entry("D1", "first")))
    save_analysis_snapshot(tmp_path, a2, build_snapshot_from_entry(_entry("D1", "second")))
    assert load_analysis_snapshot(tmp_path, "D1", "a1").ticketReport.rootCause.summary == "first"
    assert load_analysis_snapshot(tmp_path, "D1", "a2").ticketReport.rootCause.summary == "second"


def test_same_digest_is_idempotent_different_digest_rejected(tmp_path: Path):
    attempt = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a1", defectId="D1", execution="completed", resolution="analysis_only")
    snap = build_snapshot_from_entry(_entry())
    save_analysis_snapshot(tmp_path, attempt, snap)
    save_analysis_snapshot(tmp_path, attempt, snap)
    other = build_snapshot_from_entry(_entry(summary="changed"))
    with pytest.raises(SnapshotConflict):
        save_analysis_snapshot(tmp_path, attempt, other)


def test_same_digest_retry_completes_missing_attempt_and_form(tmp_path: Path):
    attempt = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a1", defectId="D1", execution="completed", resolution="analysis_only")
    snap = build_snapshot_from_entry(_entry())
    dest = tmp_path / "defects" / "D1" / "attempts" / "a1"
    dest.mkdir(parents=True, exist_ok=True)
    payload = snap.model_dump()
    payload["digest"] = snap.digest or snapshot_digest(payload)
    (dest / "analysis.json").write_text(json.dumps(payload), encoding="utf-8")
    ref = save_analysis_snapshot(tmp_path, attempt, snap)
    assert ref.digest == payload["digest"]
    assert (dest / "attempt.json").is_file()
    assert (dest / "feedback-form.md").is_file()
    assert (tmp_path / "defects" / "D1" / "latest.json").is_file()


def test_interrupted_new_attempt_retry_advances_latest(tmp_path: Path):
    a0 = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a0", defectId="D1", execution="completed", resolution="analysis_only")
    save_analysis_snapshot(tmp_path, a0, build_snapshot_from_entry(_entry("D1", "first")))
    a1 = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, attemptId="a1", defectId="D1", execution="completed", resolution="analysis_only", parentAttemptId="a0")
    snap = build_snapshot_from_entry(_entry("D1", "second"))
    dest = tmp_path / "defects" / "D1" / "attempts" / "a1"
    dest.mkdir(parents=True, exist_ok=True)
    payload = snap.model_dump()
    payload["digest"] = snap.digest or snapshot_digest(payload)
    (dest / "analysis.json").write_text(json.dumps(payload), encoding="utf-8")
    save_analysis_snapshot(tmp_path, a1, snap)
    latest = json.loads((tmp_path / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    assert latest["attemptId"] == "a1"
    save_analysis_snapshot(tmp_path, a0, build_snapshot_from_entry(_entry("D1", "first")))
    latest = json.loads((tmp_path / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    assert latest["attemptId"] == "a1"


def test_run_analyst_report_only_writes_snapshot(tmp_path: Path, monkeypatch):
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    work = tmp_path / "repo"
    work.mkdir()
    (work / "src").mkdir()
    (work / "src" / "add.py").write_text("def add(a,b):\n    return a-b\n", encoding="utf-8")
    batch = DefectBatch.model_validate({
        "schemaVersion": "0.4.0", "productLine": "hc", "posture": "alpha",
        "generatedAt": "2026-01-01T00:00:00Z", "funnel": {"total": 1, "strict": 1},
        "clusters": [], "tickets": [{
            "defectId": "D1", "title": "add swapped", "pool": "strict",
            "expectQuality": "explicit", "observed": "1+2=-1", "expected": "1+2=3",
        }],
    })
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0", "productLine": "hc", "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z", "partial": False,
        "defectCodeMatches": [{"defectId": "D1", "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}], "confidence": "medium"}],
    })
    out = tmp_path / "out"

    def analyze(req):
        payload = dict(req.routed)
        payload.update(_entry())
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    report = run_analyst(
        work_dir=work, defect_batch=batch, code_knowledge=knowledge,
        analyze_fn=analyze, artifact_dir=out, apply_fix=False,
    )
    assert report.tickets[0].attemptId
    loaded = load_analysis_snapshot(out, "D1", report.tickets[0].attemptId)
    assert "first round" in loaded.ticketReport.rootCause.summary
    assert snapshot_digest(loaded.model_dump()) == loaded.digest
