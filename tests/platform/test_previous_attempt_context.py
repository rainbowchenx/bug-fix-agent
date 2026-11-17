"""T7：resume/new/fallback 的 SDK prompt 必须看到首轮结论与答案。"""

from __future__ import annotations

from pathlib import Path

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    Feedback,
    InputRevision,
    QuestionAnswer,
    WorkspaceSnapshot,
)
from bugfix_platform.agents.analyst.analysis_store import build_snapshot_from_entry, save_analysis_snapshot
from bugfix_platform.agents.analyst.continuation import build_previous_attempt
from bugfix_platform.sdk.analyze import AnalyzeRequest, _build_prompt
from tests.platform.test_analysis_snapshots import _entry
from tests.platform.test_agent3_sdk_report import _batch


def test_prompt_contains_previous_attempt_answers(tmp_path: Path):
    attempt = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D1",
        execution="completed",
        resolution="analysis_only",
    )
    snap = build_snapshot_from_entry(_entry(), revision=InputRevision(revisionId="D1:v0", defectId="D1"))
    save_analysis_snapshot(tmp_path, attempt, snap)
    fb = Feedback(
        feedbackId="f1",
        defectId="D1",
        attemptId="a1",
        kind="supplement_fact",
        questionAnswers=[QuestionAnswer(questionId="q1", text="keep a+b", answerRevisionId="D1:f1")],
    )
    ctx = build_previous_attempt(
        tmp_path,
        "D1",
        "a1",
        current_snapshot=WorkspaceSnapshot(repoId=".", head="aaa", contentDigest="d1", capturedAt="t"),
        feedback=fb,
    )
    assert "keep a+b" in ctx.questionAnswers[0].text
    work = tmp_path / "repo"
    work.mkdir()
    ticket = _batch(work).tickets[0]
    prompt = _build_prompt(
        AnalyzeRequest(
            work_dir=str(work),
            ticket=ticket,
            routed={"outcome": "plan_only", "localization": {"candidates": []}},
            previous_attempt=ctx.model_dump(),
        )
    )
    assert "previousAttempt" in prompt
    assert "keep a+b" in prompt
    assert ctx.analysisRef.path.endswith("analysis.json")


def test_source_drift_when_dirty_changes(tmp_path: Path):
    attempt = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D1",
        execution="completed",
        resolution="analysis_only",
    )
    snap = build_snapshot_from_entry(
        _entry(),
        workspace=WorkspaceSnapshot(repoId=".", head="aaa", dirty=[], contentDigest="d1", capturedAt="t"),
    )
    save_analysis_snapshot(tmp_path, attempt, snap)
    ctx = build_previous_attempt(
        tmp_path,
        "D1",
        "a1",
        current_snapshot=WorkspaceSnapshot(repoId=".", head="aaa", dirty=["src/add.py"], contentDigest="d2", capturedAt="t2"),
    )
    assert ctx.sourceDrift is True
