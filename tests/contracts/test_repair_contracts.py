"""T01：修复契约不变量。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    EditDecision,
    Feedback,
    PatchFile,
    PatchSet,
    VerificationRun,
    validate_attempt,
)


def _patch_file(**kw):
    base = {
        "repoId": ".",
        "path": "src/a.ts",
        "kind": "modify",
        "digest": "abc",
        "archivePath": "patches/a.ts.diff",
    }
    base.update(kw)
    return PatchFile.model_validate(base)


def test_candidate_requires_complete_patch_reference():
    with pytest.raises(ValidationError, match="complete patch"):
        PatchSet.model_validate(
            {
                "patchSetId": "p1",
                "delivery": "candidate",
                "baselineHead": "0" * 40,
                "patches": [],
            }
        )
    with pytest.raises(ValidationError, match="complete patch"):
        PatchSet.model_validate(
            {
                "patchSetId": "p1",
                "delivery": "candidate",
                "baselineHead": "0" * 40,
                "patches": [
                    {
                        "repoId": ".",
                        "path": "src/a.ts",
                        "kind": "modify",
                        "digest": "",
                        "archivePath": "",
                    }
                ],
            }
        )
    ok = PatchSet.model_validate(
        {
            "patchSetId": "p1",
            "delivery": "candidate",
            "baselineHead": "0" * 40,
            "patches": [_patch_file().model_dump()],
        }
    )
    assert ok.patches[0].archivePath.endswith(".diff")


def test_passed_requires_execution_record():
    with pytest.raises(ValidationError, match="execution"):
        VerificationRun.model_validate(
            {
                "command": ["pytest"],
                "cwd": ".",
                "result": "passed",
            }
        )
    run = VerificationRun.model_validate(
        {
            "command": ["pytest", "-q"],
            "cwd": "work",
            "result": "passed",
            "exitCode": 0,
            "logRef": "checks/pytest.log",
        }
    )
    assert run.exitCode == 0


def test_accepted_only_from_feedback():
    with pytest.raises(ValidationError, match="feedback"):
        AttemptRecord.model_validate(
            {
                "schemaVersion": REPAIR_SCHEMA_VERSION,
                "attemptId": "a1",
                "defectId": "D1",
                "execution": "completed",
                "resolution": "analysis_only",
                "patchDelivery": "none",
                "userAcceptance": "accepted",
            }
        )
    fb = Feedback.model_validate(
        {
            "feedbackId": "f1",
            "defectId": "D1",
            "attemptId": "a1",
            "application": "applied",
            "acceptance": "accepted",
        }
    )
    attempt = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "patch_produced",
            "patchDelivery": "candidate",
            "userAcceptance": "accepted",
            "feedbackId": fb.feedbackId,
        }
    )
    assert attempt.userAcceptance == "accepted"


def test_old_schema_version_is_rejected():
    with pytest.raises(ValidationError, match="schemaVersion"):
        validate_attempt(
            {
                "schemaVersion": "0.1.0",
                "attemptId": "a1",
                "defectId": "D1",
                "execution": "completed",
                "resolution": "analysis_only",
                "patchDelivery": "none",
            }
        )


def test_nested_attempt_json_roundtrip():
    decision = EditDecision.model_validate(
        {
            "behaviorTarget": "失败时结束 loading",
            "codeAssociation": "src/a.ts:handleFail",
            "mechanism": "只处理成功终态",
            "editRationale": "补失败分支",
            "evidenceRefs": ["e1"],
            "allowed": True,
        }
    )
    attempt = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "patch_produced",
            "patchDelivery": "candidate",
            "editDecision": decision.model_dump(),
            "patchSet": {
                "patchSetId": "p1",
                "delivery": "candidate",
                "baselineHead": "0" * 40,
                "patches": [_patch_file().model_dump()],
            },
            "checks": [
                {
                    "command": ["pytest", "-q"],
                    "cwd": "work",
                    "result": "passed",
                    "exitCode": 0,
                    "logRef": "checks/pytest.log",
                }
            ],
        }
    )
    raw = json.loads(json.dumps(attempt.model_dump(), ensure_ascii=False))
    again = validate_attempt(raw)
    assert again.attemptId == "a1"
    assert again.patchSet.patchSetId == "p1"
    assert again.editDecision.allowed is True
    assert again.checks[0].result == "passed"
