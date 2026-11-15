"""T04：占位/未调查/失效证据不能编辑；新增文件不误拒。"""

from __future__ import annotations

from bugfix_contracts.repair import EditDecision, Evidence, TaskContext
from bugfix_platform.agents.analyst.evidence import validate_edit_decision


def _ctx(**kw) -> TaskContext:
    data = {
        "defectId": "D1",
        "evidence": [
            {
                "evidenceId": "e1",
                "category": "code_observation",
                "summary": "handleFail 只处理 success",
                "path": "src/a.ts",
                "validity": "valid",
            }
        ],
        "generatePatch": True,
    }
    data.update(kw)
    return TaskContext.model_validate(data)


def _decision(**kw) -> EditDecision:
    data = {
        "behaviorTarget": "失败时结束 loading",
        "codeAssociation": "src/a.ts:handleFail",
        "mechanism": "只处理成功终态",
        "editRationale": "补失败分支",
        "executionPremise": "generate-patch + isolated workspace",
        "evidenceRefs": ["e1"],
        "allowed": True,
    }
    data.update(kw)
    return EditDecision.model_validate(data)


def test_placeholder_or_invalid_evidence_cannot_edit():
    assert validate_edit_decision(_ctx(), _decision(mechanism="pending analysis"))
    assert validate_edit_decision(
        _ctx(evidence=[{"evidenceId": "e1", "category": "tool_result", "validity": "invalid", "summary": "x"}]),
        _decision(),
    )
    assert validate_edit_decision(
        _ctx(evidence=[]),
        _decision(),
    )


def test_new_file_caller_check_can_pass():
    ctx = _ctx(
        evidence=[
            {
                "evidenceId": "e1",
                "category": "code_observation",
                "summary": "login.vue 调用新 helper",
                "path": "src/login.vue",
                "validity": "valid",
            },
            {
                "evidenceId": "e2",
                "category": "code_observation",
                "summary": "新增 src/failState.ts 供 login 调用",
                "path": "src/failState.ts",
                "validity": "valid",
            },
        ]
    )
    decision = _decision(
        codeAssociation="src/failState.ts (new) called from src/login.vue",
        evidenceRefs=["e1", "e2"],
    )
    assert validate_edit_decision(ctx, decision) == []


def test_valid_static_decision_is_allowed():
    assert validate_edit_decision(_ctx(), _decision()) == []


def test_pending_review_code_observation_cannot_edit():
    ctx = _ctx(
        evidence=[
            {
                "evidenceId": "e1",
                "category": "code_observation",
                "summary": "path exists",
                "path": "src/a.ts",
                "validity": "pending_review",
            }
        ]
    )
    assert validate_edit_decision(ctx, _decision())


def test_open_questions_cannot_edit():
    assert validate_edit_decision(_ctx(), _decision(openQuestions=["which device model"]))
