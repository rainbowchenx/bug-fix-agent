"""T11 / T13：feedback 与 resume 子命令。"""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord
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
    assert "camera_disconnected" in payload["revision"]["observed"]


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
