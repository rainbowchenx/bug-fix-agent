"""T8：产品 choice 不能自行 resolved；已答问题必须保留。"""

from __future__ import annotations

from bugfix_contracts.repair import (
    AnalysisSnapshotRef,
    EditDecision,
    Evidence,
    InputRevision,
    PreviousAttemptContext,
    Question,
    QuestionAnswer,
    QuestionResolution,
    TaskContext,
)
from bugfix_platform.agents.analyst.continuation import consume_question_answers
from bugfix_platform.agents.analyst.evidence import validate_edit_decision


def _prev(**kwargs) -> PreviousAttemptContext:
    data = dict(
        attemptId="a1",
        digest="d" * 64,
        analysisRef=AnalysisSnapshotRef(path="x", digest="d" * 64, attemptId="a1"),
        outcome="plan_only",
        confirmedTarget="add should return a+b",
        openQuestions=[
            Question(id="q1", kind="choice", reason="product target?", category="product", relatedClaimIds=[]),
            Question(id="q2", kind="choice", reason="use map or for?", category="implementation", relatedClaimIds=[]),
        ],
        questionAnswers=[],
        questionResolutions=[],
    )
    data.update(kwargs)
    return PreviousAttemptContext.model_validate(data)


def test_user_business_answer_resolves_and_implementation_can_self_decide():
    evidence = [Evidence(evidenceId="e1", category="code_observation", validity="valid")]
    prev = _prev(questionAnswers=[QuestionAnswer(questionId="q1", text="keep a+b", answerRevisionId="r1")])
    revision = InputRevision(
        revisionId="r1",
        defectId="D1",
        questionAnswers=[QuestionAnswer(questionId="q1", text="keep a+b", answerRevisionId="r1")],
    )
    proposed = [
        Question(
            id="q1", kind="choice", reason="user confirmed a+b", category="product",
            status="resolved", relatedClaimIds=["c1"], newEvidenceRefs=["e1"],
        ),
        Question(
            id="q2", kind="choice", reason="use for-loop", category="implementation",
            status="resolved", relatedClaimIds=[], newEvidenceRefs=["e1"],
        ),
    ]
    result = consume_question_answers(prev, revision, proposed, evidence, revision_id="r1")
    by_id = {r.questionId: r for r in result.resolutions}
    assert by_id["q1"].resolutionSource == "user_answer"
    assert by_id["q1"].disposition == "resolved"
    assert by_id["q2"].resolutionSource == "agent_decision"
    assert not any(q.id == "q1" and q.status == "open" for q in result.openQuestions)


def test_unanswered_product_choice_cannot_be_agent_resolved():
    prev = _prev()
    proposed = [
        Question(id="q1", kind="choice", reason="I picked X", category="product", status="resolved", relatedClaimIds=[]),
    ]
    result = consume_question_answers(prev, None, proposed, [], revision_id="r1")
    assert any(q.id == "q1" for q in result.openQuestions)
    assert all(r.questionId != "q1" or r.resolutionSource != "agent_decision" for r in result.resolutions)


def test_omitted_parent_question_still_blocks():
    prev = _prev()
    result = consume_question_answers(prev, None, [], [], revision_id="r1")
    assert result.needsClosingPass
    assert any("omitted parent question q1" in v for v in result.violations)


def test_rewrite_without_predecessor_is_protocol_gap():
    prev = _prev()
    proposed = [
        Question(id="q9", kind="choice", reason="new wording", category="product", relatedClaimIds=[]),
    ]
    result = consume_question_answers(prev, None, proposed, [], revision_id="r1")
    assert any("predecessorId" in v or "omitted" in v for v in result.violations)


def test_resolved_blocking_requires_matching_resolution():
    evidence = [Evidence(evidenceId="e1", category="code_observation", validity="valid")]
    ctx = TaskContext(
        defectId="D1",
        generatePatch=True,
        evidence=evidence,
        currentTarget="a+b",
    )
    decision = EditDecision(
        behaviorTarget="a+b",
        codeAssociation="src/add.py",
        mechanism="swap operands",
        editRationale="restore addition",
        evidenceRefs=["e1"],
        questions=[
            Question(id="q1", kind="choice", reason="done", category="product", status="resolved", relatedClaimIds=[]),
            Question(id="v1", kind="verification", reason="retest", category="follow_up", relatedClaimIds=[]),
        ],
    )
    assert "resolved question lacks matching resolution" in validate_edit_decision(ctx, decision)
    ctx2 = ctx.model_copy(update={
        "questionResolutions": [
            QuestionResolution(
                questionId="q1",
                resolutionSource="user_answer",
                revisionId="r1",
                answerRevisionId="r1",
                targetDigest="a" * 64,
                disposition="resolved",
                resolutionSummary="keep a+b",
                evidenceRefs=["e1"],
            )
        ]
    })
    assert validate_edit_decision(ctx2, decision) == []


def test_answered_and_incomplete_still_block_edit():
    ctx = TaskContext(
        defectId="D1",
        generatePatch=True,
        evidence=[Evidence(evidenceId="e1", category="code_observation", validity="valid")],
        currentTarget="a+b",
        analysisIncomplete=True,
    )
    decision = EditDecision(
        behaviorTarget="a+b",
        codeAssociation="src/add.py",
        mechanism="swap operands",
        editRationale="restore addition",
        evidenceRefs=["e1"],
        questions=[
            Question(id="q1", kind="choice", reason="?", category="product", status="answered", relatedClaimIds=[]),
        ],
    )
    errors = validate_edit_decision(ctx, decision)
    assert "analysis incomplete" in errors
    assert "blocking question unresolved" in errors


def test_short_unknown_answers_do_not_auto_resolve():
    prev = _prev(questionAnswers=[QuestionAnswer(questionId="q1", text="不知道", answerRevisionId="r1")])
    revision = InputRevision(
        revisionId="r1",
        defectId="D1",
        questionAnswers=[QuestionAnswer(questionId="q1", text="不知道", answerRevisionId="r1")],
    )
    proposed = [
        Question(id="q1", kind="choice", reason="product target?", category="product", relatedClaimIds=[]),
    ]
    result = consume_question_answers(prev, revision, proposed, [], revision_id="r1")
    assert any(q.id == "q1" for q in result.openQuestions)
    assert all(r.disposition != "resolved" for r in result.resolutions if r.questionId == "q1")


def test_candidate_alias_resolves_implementation_question():
    evidence = [Evidence(evidenceId="read-D1-1", category="code_observation", validity="valid")]
    prev = _prev()
    proposed = [
        Question(
            id="q2",
            kind="choice",
            reason="use for-loop",
            category="implementation",
            status="resolved",
            newEvidenceRefs=["candidate:1"],
            relatedClaimIds=[],
        ),
        Question(id="q1", kind="choice", reason="product target?", category="product", relatedClaimIds=[]),
    ]
    result = consume_question_answers(
        prev,
        None,
        proposed,
        evidence,
        revision_id="r1",
        evidence_aliases={"candidate:1": "read-D1-1", "src/add.py": "read-D1-1"},
    )
    by_id = {r.questionId: r for r in result.resolutions}
    assert by_id["q2"].disposition == "resolved"
    assert by_id["q2"].evidenceRefs == ["read-D1-1"]


def test_resolved_question_cannot_reopen_without_new_evidence():
    evidence = [Evidence(evidenceId="e1", category="code_observation", validity="valid")]
    prev = _prev(
        openQuestions=[],
        questionLedger=[
            Question(id="q1", kind="choice", reason="product target?", category="product", status="resolved", relatedClaimIds=[]),
        ],
        questionResolutions=[
            QuestionResolution(
                questionId="q1",
                resolutionSource="user_answer",
                revisionId="r0",
                answerRevisionId="r0",
                targetDigest=__import__("hashlib").sha256(b"add should return a+b").hexdigest(),
                disposition="resolved",
                resolutionSummary="keep a+b",
                evidenceRefs=["e1"],
            )
        ],
        questionAnswers=[QuestionAnswer(questionId="q1", text="keep a+b", answerRevisionId="r0")],
    )
    proposed = [
        Question(id="q1", kind="choice", reason="ask again", category="product", status="open", relatedClaimIds=[]),
    ]
    result = consume_question_answers(prev, None, proposed, evidence, revision_id="r1")
    assert any("reopen of q1" in v for v in result.violations)
    assert result.analysisIncomplete is True


def test_expected_change_invalidates_old_resolution():
    old_td = __import__("hashlib").sha256(b"add should return a+b").hexdigest()
    prev = _prev(
        questionResolutions=[
            QuestionResolution(
                questionId="q1",
                resolutionSource="user_answer",
                revisionId="r0",
                answerRevisionId="r0",
                targetDigest=old_td,
                disposition="resolved",
                resolutionSummary="old target",
                evidenceRefs=["e1"],
            )
        ]
    )
    revision = InputRevision(revisionId="r1", defectId="D1", expected="return a-b instead")
    result = consume_question_answers(prev, revision, [], [], revision_id="r1")
    assert all(r.questionId != "q1" or r.disposition != "resolved" for r in result.resolutions)
