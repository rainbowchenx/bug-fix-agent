"""T11 / T13：feedback 与 resume 子命令。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, Feedback
from bugfix_platform.agents.analyst.attempt_store import save_attempt
from bugfix_platform.cli import main


def test_feedback_cli_imports_file(tmp_path: Path):
    root = tmp_path / "out"
    path = tmp_path / "fb.json"
    path.write_text(
        json.dumps(
            {
                "feedbackId": "f1",
                "defectId": "D1",
                "attemptId": "a1",
                "application": "not_applied",
                "acceptance": "rejected",
                "text": "补充：camera_disconnected",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rc = main(["feedback", "--root", str(root), "--file", str(path)])
    assert rc == 0
    dest = root / "defects" / "D1" / "feedback" / "f1.json"
    assert dest.is_file()
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert "camera_disconnected" in payload["revision"]["feedbackText"]


def test_resume_cli_writes_decision_without_cwd_guess(tmp_path: Path):
    root = tmp_path / "out"
    save_attempt(
        root,
        AttemptRecord.model_validate(
            {
                "schemaVersion": REPAIR_SCHEMA_VERSION,
                "attemptId": "a1",
                "defectId": "D1",
                "execution": "completed",
                "resolution": "needs_information",
                "patchDelivery": "none",
            }
        ),
    )
    rc = main(["resume", "--root", str(root), "--defect-id", "D1"])
    assert rc == 0
    dest = root / "defects" / "D1" / "session-decision.json"
    assert dest.is_file()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["action"] in ("resume", "new")
    assert data.get("sessionId") != "cwd-recent"


@pytest.mark.parametrize("old_report", ["truncated", "invalid", "stale"])
def test_resume_reconciles_committed_snapshots(tmp_path: Path, monkeypatch, old_report):
    from bugfix_contracts import CodeKnowledge, DefectBatch
    from bugfix_platform.agents.analyst.analysis_store import build_snapshot_from_entry, save_analysis_snapshot
    from bugfix_platform.agents.analyst.report_store import load_or_rebuild_analysis_report
    from bugfix_platform.sdk.analyze import AnalyzeResult
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    from tests.helpers import ensure_git_repo
    from tests.platform.test_analysis_snapshots import _entry

    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.ensure_codegraph",
        lambda *a, **k: CodeGraphStatus(ready=False),
    )
    root = tmp_path / "out"
    work = tmp_path / "repo"
    ensure_git_repo(work)
    (work / "src").mkdir()
    (work / "src" / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    batch = DefectBatch.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "posture": "alpha",
        "generatedAt": "2026-01-01T00:00:00Z",
        "funnel": {"total": 2, "strict": 2},
        "clusters": [],
        "tickets": [
            {
                "defectId": "D1",
                "title": "add",
                "pool": "strict",
                "expectQuality": "explicit",
                "observed": "1+2=-1",
                "expected": "1+2=3",
            },
            {
                "defectId": "D2",
                "title": "other",
                "pool": "strict",
                "expectQuality": "explicit",
                "observed": "x",
                "expected": "y",
            },
        ],
    })
    knowledge = CodeKnowledge.model_validate({
        "schemaVersion": "0.4.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "partial": False,
        "defectCodeMatches": [
            {"defectId": "D1", "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}], "confidence": "medium"},
            {"defectId": "D2", "candidates": [{"path": "src/add.py", "source": "grep", "why": "add"}], "confidence": "medium"},
        ],
    })
    root.mkdir()
    (root / "defect-batch.json").write_text(batch.model_dump_json(), encoding="utf-8")
    (root / "code-knowledge.json").write_text(knowledge.model_dump_json(), encoding="utf-8")
    a1 = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D2",
        execution="completed",
        resolution="analysis_only",
    )
    save_analysis_snapshot(root, a1, build_snapshot_from_entry(_entry("D2", "keep other")))
    rebuilt = load_or_rebuild_analysis_report(
        root, product_line="hc", work_dir=str(work), apply_fix=False
    )
    assert rebuilt is not None
    assert any(t.defectId == "D2" for t in rebuilt.tickets)
    report_path = root / "analysis-report.json"
    if old_report == "truncated":
        report_path.write_text('{"schemaVersion":"0.4.0",', encoding="utf-8")
    elif old_report == "invalid":
        report_path.write_text("{}", encoding="utf-8")
    else:
        outdated = rebuilt.model_dump()
        outdated["tickets"][0]["attemptId"] = "old-d2"
        report_path.write_text(json.dumps(outdated), encoding="utf-8")

    def analyze(req):
        payload = dict(req.routed)
        payload.update(_entry("D1", "rebuilt resume"))
        payload["rootCause"]["questions"] = []
        return AnalyzeResult(ok=True, payload=payload, source="sdk")

    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.create_analyze_runner",
        lambda *a, **k: analyze,
    )
    from bugfix_platform.agents.analyst.run import run_analyst

    args = ["resume", "--root", str(root), "--defect-id", "D1", "--execute"]
    competing = []

    def run_with_competing_resume(**kwargs):
        if not competing:
            competing.append(None)
            competing[0] = main(args)
        return run_analyst(**kwargs)

    monkeypatch.setattr("bugfix_platform.agents.analyst.run.run_analyst", run_with_competing_resume)
    rc = main(args)
    assert competing == [1]
    assert rc == 0
    report = json.loads((root / "analysis-report.json").read_text(encoding="utf-8"))
    ids = {t["defectId"] for t in report["tickets"]}
    assert "D1" in ids
    assert "D2" in ids
    assert next(t for t in report["tickets"] if t["defectId"] == "D2")["attemptId"] == "a1"


def test_resume_cli_rejects_stale_revision_and_keeps_latest_parent(tmp_path, monkeypatch, capsys):
    from bugfix_contracts import AnalysisReport
    from bugfix_platform.agents.analyst.analysis_store import build_snapshot_from_entry, save_analysis_snapshot
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from tests.platform.test_analysis_snapshots import _entry
    from tests.platform.test_repair_entry import _batch, _knowledge

    root = tmp_path / "out"
    root.mkdir()
    work = tmp_path / "repo"
    work.mkdir()
    (root / "defect-batch.json").write_text(_batch().model_dump_json(), encoding="utf-8")
    (root / "code-knowledge.json").write_text(_knowledge(work).model_dump_json(), encoding="utf-8")

    def save_round(attempt_id, *, revision_id=None, parent=None):
        attempt = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, defectId="D1", attemptId=attempt_id,
                                parentAttemptId=parent, revisionId=revision_id, resolution="needs_information")
        save_analysis_snapshot(root, attempt, build_snapshot_from_entry({**_entry(), "attemptId": attempt_id}))

    save_round("a1")
    for ident, expected in (("f1", "obsolete"), ("f2", "agreed")):
        import_feedback(root, Feedback(defectId="D1", feedbackId=ident, attemptId="a1", expected=expected))
    save_round("a2", revision_id="D1:f2", parent="a1")
    save_round("a3", revision_id="D1:f2", parent="a2")

    calls = []

    def analyze(**kwargs):
        calls.append(kwargs)
        return AnalysisReport(schemaVersion="0.4.0", productLine="hc", workDir=str(work),
                              generatedAt="2026-01-01", tickets=[])

    monkeypatch.setattr("bugfix_platform.agents.analyst.run.run_analyst", analyze)
    args = ["resume", "--root", str(root), "--defect-id", "D1"]
    assert main(args + ["--revision-id", "D1:f1"]) == 0  # Historical preview is still available.
    for mode in ("--execute", "--apply-fix"):
        assert main(args + [mode, "--revision-id", "D1:f1"]) == 1
    assert not calls
    assert "current revision: D1:f2" in capsys.readouterr().err

    assert main(args + ["--apply-fix", "--revision-id", "D1:f2"]) == 0
    assert calls[-1]["revisions"]["D1"].expected == "agreed"
    assert calls[-1]["parent_attempt_ids"] == {"D1": "a3"}

    import_feedback(root, Feedback(defectId="D1", feedbackId="f3", attemptId="a2", expected="stale parent"))
    assert main(args + ["--apply-fix"]) == 1
    assert len(calls) == 1
    assert "current attempt: a3" in capsys.readouterr().err
