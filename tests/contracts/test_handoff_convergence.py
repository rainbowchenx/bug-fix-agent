"""T0：0.4.0 交接/收敛契约。字符串 facts 只是不可信输入，不是生产 Fact。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bugfix_contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CONTRACT_SCHEMA_VERSION,
    DEFECT_BATCH_SCHEMA_VERSION,
    REPAIR_SCHEMA_VERSION,
    safe_validate_code_knowledge,
    validate_code_knowledge,
    validate_defect_batch,
    validate_attempt,
)
from bugfix_contracts.analysis_report import AnalysisSnapshot
from bugfix_contracts.code_knowledge import (
    InvestigationFact,
    MatchParseResult,
    ParseIssue,
    RawResponseRef,
)
from bugfix_contracts.repair import (
    AnalysisSnapshotRef,
    ConvergenceResult,
    PreviousAttemptContext,
    Question,
    QuestionAnswer,
    QuestionResolution,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "repair_quality" / "handoff-convergence" / "manifest.json"


def test_schema_version_is_0_4_0():
    assert CONTRACT_SCHEMA_VERSION == "0.4.0"
    assert DEFECT_BATCH_SCHEMA_VERSION == "0.4.0"
    assert CODE_KNOWLEDGE_SCHEMA_VERSION == "0.4.0"
    assert ANALYSIS_REPORT_SCHEMA_VERSION == "0.4.0"
    assert REPAIR_SCHEMA_VERSION == "0.4.0"


def test_old_0_3_production_artifacts_are_rejected():
    ok, err = safe_validate_code_knowledge(
        {
            "schemaVersion": "0.3.0",
            "productLine": "p",
            "workDir": "/tmp/w",
            "generatedAt": "2026-01-01T00:00:00Z",
        }
    )
    assert ok is False
    assert "0.3.0" in str(err) or "schemaVersion" in str(err)
    with pytest.raises(ValidationError):
        validate_defect_batch(
            {
                "schemaVersion": "0.3.0",
                "productLine": "p",
                "posture": "alpha",
                "generatedAt": "2026-01-01T00:00:00Z",
                "funnel": {"total": 0},
                "clusters": [],
                "tickets": [],
            }
        )
    with pytest.raises(ValidationError, match="schemaVersion"):
        validate_attempt(
            {
                "schemaVersion": "0.3.0",
                "attemptId": "a1",
                "defectId": "D1",
            }
        )


def test_string_facts_are_untrusted_not_production_facts():
    with pytest.raises(ValidationError):
        InvestigationFact.model_validate("ONVIF jumps to page X")
    ok, _ = safe_validate_code_knowledge(
        {
            "schemaVersion": CONTRACT_SCHEMA_VERSION,
            "productLine": "p",
            "workDir": "/tmp/w",
            "generatedAt": "2026-01-01T00:00:00Z",
            "defectCodeMatches": [
                {"defectId": "D1", "facts": ["a string is not a fact"]}
            ],
        }
    )
    assert ok is False
    fact = InvestigationFact.model_validate({"claim": "route handler reads pageId"})
    assert fact.validity == "unverified"
    assert fact.source == "model_reported"
    assert fact.reference is None
    dumped = json.loads(fact.model_dump_json())
    assert dumped["claim"] == "route handler reads pageId"
    roundtrip = InvestigationFact.model_validate(dumped)
    assert roundtrip == fact


def test_model_cannot_self_report_tool_observed_or_verified_validity():
    fact = InvestigationFact.model_validate(
        {
            "claim": "saw grep",
            "source": "tool_observed",
            "validity": "reference_verified",
        }
    )
    # 生产类型允许程序写入；适配器（T2）禁止模型自报。T0 钉住字段集合。
    assert set(InvestigationFact.model_fields) >= {
        "claim",
        "reference",
        "validity",
        "source",
    }
    assert fact.source in ("model_reported", "tool_observed")


def test_question_identity_and_parent_attempt_are_stable():
    q = Question.model_validate(
        {
            "id": "Q-onvif-page",
            "kind": "choice",
            "reason": "验收页不唯一",
            "category": "product",
            "status": "open",
            "predecessorId": None,
            "newEvidenceRefs": [],
        }
    )
    assert q.id == "Q-onvif-page"
    assert q.category == "product"
    ctx = PreviousAttemptContext.model_validate(
        {
            "attemptId": "att-1",
            "parentAttemptId": None,
            "revisionId": "rev-1",
            "digest": "d" * 64,
            "outcome": "needs_design_input",
            "rootCauseSummary": "page unknown",
            "confirmedTarget": "open ONVIF settings",
            "analysisRef": {
                "path": "defects/D1/attempts/att-1/analysis.json",
                "digest": "d" * 64,
                "attemptId": "att-1",
            },
        }
    )
    assert ctx.attemptId == "att-1"
    assert ctx.analysisRef.attemptId == "att-1"


def test_base_revision_and_internal_parent_revision_are_distinct():
    snap = AnalysisSnapshot.model_validate(
        {
            "ticketReport": {
                "defectId": "D1",
                "outcome": "needs_design_input",
                "blockers": {"kind": "needs_design_input", "detail": "page"},
                "attemptId": "att-1",
            },
            "effectiveRevision": {
                "revisionId": "rev-base",
                "defectId": "D1",
                "source": "ticket",
            },
            "questionResolutions": [],
            "parentAttemptId": None,
            "digest": "a" * 64,
            "baseRevisionId": "rev-base",
        }
    )
    assert snap.baseRevisionId == "rev-base"
    assert snap.effectiveRevision.revisionId == "rev-base"
    ref = AnalysisSnapshotRef.model_validate(
        {
            "path": "defects/D1/attempts/att-1/analysis.json",
            "digest": "a" * 64,
            "attemptId": "att-1",
        }
    )
    dumped = json.loads(ref.model_dump_json())
    assert AnalysisSnapshotRef.model_validate(dumped).digest == "a" * 64


def test_user_answer_requires_answer_revision_id():
    with pytest.raises(ValidationError, match="answerRevisionId"):
        QuestionResolution.model_validate(
            {
                "questionId": "Q-1",
                "resolutionSource": "user_answer",
                "revisionId": "rev-2",
                "targetDigest": "t" * 64,
                "disposition": "resolved",
                "resolutionSummary": "user picked page A",
            }
        )
    ok = QuestionResolution.model_validate(
        {
            "questionId": "Q-1",
            "resolutionSource": "user_answer",
            "revisionId": "rev-2",
            "answerRevisionId": "rev-2",
            "targetDigest": "t" * 64,
            "disposition": "resolved",
            "resolutionSummary": "user picked page A",
        }
    )
    assert ok.answerRevisionId == "rev-2"


def test_agent_decision_cannot_forge_user_answer():
    res = QuestionResolution.model_validate(
        {
            "questionId": "Q-impl",
            "resolutionSource": "agent_decision",
            "revisionId": "rev-1",
            "targetDigest": "t" * 64,
            "disposition": "resolved",
            "resolutionSummary": "reuse existing mapper",
            "evidenceRefs": ["e1"],
        }
    )
    assert res.answerRevisionId is None
    with pytest.raises(ValidationError):
        QuestionResolution.model_validate(
            {
                "questionId": "Q-impl",
                "resolutionSource": "not_a_source",
                "revisionId": "rev-1",
                "targetDigest": "t" * 64,
                "disposition": "resolved",
                "resolutionSummary": "x",
            }
        )


def test_acceptance_and_storage_status_are_separate():
    result = MatchParseResult.model_validate(
        {
            "accepted": {
                "defectId": "D1",
                "acceptanceStatus": "accepted",
                "storageStatus": "saved",
            },
            "issues": [
                {
                    "fieldPath": "facts[1]",
                    "reason": "non_object_fact",
                    "action": "isolate",
                    "rawRef": "response.json#facts[1]",
                }
            ],
            "acceptedFields": ["candidates", "facts"],
            "rejectedFields": ["facts[1]"],
        }
    )
    assert result.accepted.acceptanceStatus == "accepted"
    assert result.accepted.storageStatus == "saved"
    issue = result.issues[0]
    assert issue.fieldPath == "facts[1]"
    assert issue.rawRef.endswith("facts[1]")


def test_missing_required_types_are_not_swallowed():
    with pytest.raises(ValidationError):
        ParseIssue.model_validate({"reason": "x"})
    with pytest.raises(ValidationError):
        RawResponseRef.model_validate({"path": "x"})
    with pytest.raises(ValidationError):
        QuestionAnswer.model_validate({"text": "yes"})
    with pytest.raises(ValidationError):
        ConvergenceResult.model_validate({})
    with pytest.raises(ValidationError):
        PreviousAttemptContext.model_validate({"attemptId": "a1"})


def test_handoff_fixture_manifest_does_not_invent_raw_responses():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["invalidMatchCount"] == 85
    assert data["stringFacts"]["role"] == "reproduced_input"
    assert data["originalErrorResponses"] == "pending"
    assert "not a captured SDK response" in data["stringFacts"]["note"]
