"""首轮上下文贯穿续跑，以及问题答案消费。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.repair import (
    ConvergenceResult,
    Feedback,
    InputRevision,
    PreviousAttemptContext,
    Question,
    QuestionAnswer,
    QuestionResolution,
    WorkspaceSnapshot,
)
from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot
from bugfix_platform.agents.analyst.feedback import classify_patch_state


def target_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_previous_attempt(
    root: Path | str,
    defect_id: str,
    parent_attempt_id: str,
    current_snapshot: Optional[WorkspaceSnapshot] = None,
    feedback: Optional[Feedback] = None,
    patch=None,
) -> PreviousAttemptContext:
    snapshot = load_analysis_snapshot(root, defect_id, parent_attempt_id)
    report = snapshot.ticketReport
    if feedback is None:
        from bugfix_platform.agents.analyst.feedback import load_latest_feedback
        feedback = load_latest_feedback(Path(root), defect_id)
    if patch is None:
        attempt_path = Path(root) / "defects" / defect_id / "attempts" / parent_attempt_id / "attempt.json"
        if attempt_path.is_file():
            from bugfix_platform.agents.analyst.attempt_store import load_attempt
            try:
                patch = load_attempt(attempt_path).patchSet
            except (OSError, ValueError):
                patch = None
    parent_ws = snapshot.workspaceSnapshot
    current_head = current_snapshot.head if current_snapshot is not None else None
    current_digest = current_snapshot.contentDigest if current_snapshot is not None else None
    parent_head = parent_ws.head if parent_ws is not None else None
    parent_digest = parent_ws.contentDigest if parent_ws is not None else None
    source_drift = bool(
        (parent_head and current_head and parent_head != current_head)
        or (parent_digest and current_digest and parent_digest != current_digest)
        or (parent_ws and current_snapshot and parent_ws.dirty != current_snapshot.dirty)
    )
    answers = list((feedback.questionAnswers if feedback else None) or [])
    if snapshot.effectiveRevision is not None:
        for item in snapshot.effectiveRevision.questionAnswers:
            if all(item.questionId != a.questionId for a in answers):
                answers.append(item)
    rejected = []
    if feedback is not None and feedback.kind == "reject_hypothesis":
        rejected.append(feedback.text)
    patch_state = None
    if patch is not None:
        snap = current_snapshot or parent_ws
        if snap is not None:
            patch_state = str(classify_patch_state(patch, snap).get("application") or "unknown")
    return PreviousAttemptContext(
        attemptId=parent_attempt_id,
        parentAttemptId=snapshot.parentAttemptId,
        revisionId=snapshot.baseRevisionId,
        digest=snapshot.digest,
        workspaceHead=parent_head,
        contentDigest=parent_digest,
        currentHead=current_head,
        currentContentDigest=current_digest,
        sourceDrift=source_drift,
        outcome=report.outcome,
        topCandidates=[c.model_dump() for c in (report.localization.candidates or [])[:5]],
        rootCauseSummary=report.rootCause.summary if report.rootCause else "",
        claims=list(report.rootCause.claims or []) if report.rootCause else [],
        ruledOut=list(report.rootCause.ruledOut or []) if report.rootCause else [],
        proposedFix=report.proposedFix.model_dump() if report.proposedFix else None,
        openQuestions=list(report.rootCause.questions or []) if report.rootCause else [],
        questionLedger=list(snapshot.questionLedger or report.rootCause.questions or []) if report.rootCause else list(snapshot.questionLedger or []),
        questionResolutions=list(snapshot.questionResolutions or []),
        confirmedTarget=(report.ticket.expected or "") if report.ticket else "",
        latestFeedbackKind=feedback.kind if feedback else None,
        latestFeedbackText=(feedback.text if feedback else "") or "",
        rejectedHypotheses=rejected,
        patchState=patch_state,
        analysisRef={
            "path": str(Path(root) / "defects" / defect_id / "attempts" / parent_attempt_id / "analysis.json"),
            "digest": snapshot.digest,
            "attemptId": parent_attempt_id,
        },
        questionAnswers=answers,
    )


def _answer_map(revision: Optional[InputRevision], previous: PreviousAttemptContext) -> dict[str, QuestionAnswer]:
    out: dict[str, QuestionAnswer] = {}
    for item in previous.questionAnswers:
        out[item.questionId] = item
    if revision is not None:
        for item in revision.questionAnswers:
            out[item.questionId] = item
    return out


def _evidence_ids(current_evidence: list[Any]) -> set[str]:
    ids = {
        getattr(e, "evidenceId", None) or (e.get("evidenceId") if isinstance(e, dict) else None)
        for e in current_evidence
    }
    ids.discard(None)
    return {str(x) for x in ids}


def _rewrite_refs(refs: list[Any], aliases: dict[str, str]) -> list[str]:
    out: list[str] = []
    for raw in refs or []:
        text = str(raw).strip()
        if not text:
            continue
        out.append(aliases.get(text, text))
    return out


def _merge_parent_questions(previous: PreviousAttemptContext) -> list[Question]:
    by_id: dict[str, Question] = {}
    for question in list(previous.questionLedger or []) + list(previous.openQuestions or []):
        by_id.setdefault(question.id, question)
    return list(by_id.values())


def consume_question_answers(
    previous: PreviousAttemptContext,
    revision: Optional[InputRevision],
    proposed_questions: list[Question],
    current_evidence: list[Any],
    *,
    revision_id: str = "round",
    evidence_aliases: Optional[dict[str, str]] = None,
) -> ConvergenceResult:
    """由分析会话给出处理结论，程序只校验引用/状态/目标；不靠字数或关键词判业务。"""
    answers = _answer_map(revision, previous)
    aliases = dict(evidence_aliases or {})
    parent_questions = _merge_parent_questions(previous)
    proposed = list(proposed_questions or [])
    proposed_by_id = {q.id: q for q in proposed}
    parent_ids = {q.id for q in parent_questions}
    current_target = ""
    if revision is not None and revision.expected:
        current_target = revision.expected
    elif previous.confirmedTarget:
        current_target = previous.confirmedTarget
    td = target_digest(current_target)
    expected_changed = bool(
        revision is not None and previous.confirmedTarget and revision.expected
        and revision.expected != previous.confirmedTarget
    )
    resolutions: list[QuestionResolution] = []
    invalidated_ids: set[str] = set()
    for item in previous.questionResolutions or []:
        if expected_changed and item.targetDigest != td:
            invalidated_ids.add(item.questionId)
            resolutions.append(
                QuestionResolution(
                    questionId=item.questionId,
                    resolutionSource="agent_decision",
                    revisionId=revision.revisionId if revision is not None else revision_id,
                    targetDigest=td,
                    disposition="insufficient",
                    resolutionSummary="expected changed; restatement required",
                    evidenceRefs=list(item.evidenceRefs or []),
                )
            )
            continue
        resolutions.append(item)
    resolved_ids = {r.questionId for r in resolutions if r.disposition == "resolved"}
    violations: list[str] = []
    open_questions: list[Question] = []
    evidence_ids = _evidence_ids(current_evidence)

    def _keep_open(question: Question, status: str = "open") -> None:
        open_questions.append(question.model_copy(update={"status": status}))

    for question in parent_questions:
        incoming = proposed_by_id.get(question.id)
        answer = answers.get(question.id)
        if incoming is None:
            rewritten = [q for q in proposed if q.predecessorId == question.id]
            if not rewritten and question.kind in {"blocking", "choice"} and question.id not in resolved_ids:
                if question.id in invalidated_ids:
                    violations.append(f"expected changed; restatement required for {question.id}")
                else:
                    violations.append(f"omitted parent question {question.id}")
                _keep_open(question, "open")
                continue
            incoming = rewritten[0] if rewritten else question
        if incoming.id != question.id and not incoming.predecessorId:
            violations.append(f"rewritten question {incoming.id} missing predecessorId")
        incoming_refs = _rewrite_refs(incoming.newEvidenceRefs or [], aliases)
        if incoming_refs != list(incoming.newEvidenceRefs or []):
            incoming = incoming.model_copy(update={"newEvidenceRefs": incoming_refs})
        if question.id in resolved_ids and incoming.status == "open" and not incoming.newEvidenceRefs:
            violations.append(f"reopen of {question.id} without new evidence")
            continue
        model_resolved = incoming.status == "resolved"
        refs = incoming_refs
        refs_ok = bool(refs) and all(ref in evidence_ids for ref in refs)

        if model_resolved and question.kind in {"blocking", "choice"} and incoming.category in {"product", "fact"}:
            if answer and answer.text.strip() and (refs_ok or incoming.relatedClaimIds):
                resolutions.append(
                    QuestionResolution(
                        questionId=question.id,
                        resolutionSource="user_answer",
                        revisionId=revision.revisionId if revision is not None else revision_id,
                        answerRevisionId=answer.answerRevisionId or (revision.revisionId if revision else revision_id),
                        targetDigest=td,
                        disposition="resolved",
                        resolutionSummary=(incoming.reason or answer.text)[:500],
                        evidenceRefs=refs,
                    )
                )
                resolved_ids.add(question.id)
                continue
            if answer and answer.text.strip():
                resolutions.append(
                    QuestionResolution(
                        questionId=question.id,
                        resolutionSource="user_answer",
                        revisionId=revision.revisionId if revision is not None else revision_id,
                        answerRevisionId=answer.answerRevisionId or (revision.revisionId if revision else revision_id),
                        targetDigest=td,
                        disposition="insufficient",
                        resolutionSummary=(incoming.reason or answer.text)[:500],
                        evidenceRefs=refs,
                    )
                )
            _keep_open(question, "answered" if answer and answer.text.strip() else "open")
            continue
        if model_resolved and incoming.category == "implementation" and refs_ok:
            resolutions.append(
                QuestionResolution(
                    questionId=question.id,
                    resolutionSource="agent_decision",
                    revisionId=revision_id,
                    targetDigest=td,
                    disposition="resolved",
                    resolutionSummary=(incoming.reason or "implementation decision")[:500],
                    evidenceRefs=refs,
                )
            )
            resolved_ids.add(question.id)
            continue
        if incoming.kind in {"blocking", "choice"}:
            status = "answered" if answer and answer.text.strip() else "open"
            _keep_open(incoming if incoming.id == question.id else question, status)
            continue
        open_questions.append(incoming)

    for question in proposed:
        if question.id in parent_ids or question.predecessorId in parent_ids:
            continue
        if question.kind in {"blocking", "choice"} and not question.reason:
            violations.append(f"new blocking question {question.id} lacks first-seen rationale")
        refs = _rewrite_refs(question.newEvidenceRefs or [], aliases)
        if refs != list(question.newEvidenceRefs or []):
            question = question.model_copy(update={"newEvidenceRefs": refs})
        refs_ok = bool(refs) and all(ref in evidence_ids for ref in refs)
        if question.status == "resolved" and question.category == "implementation" and refs_ok:
            resolutions.append(
                QuestionResolution(
                    questionId=question.id,
                    resolutionSource="agent_decision",
                    revisionId=revision_id,
                    targetDigest=td,
                    disposition="resolved",
                    resolutionSummary=(question.reason or "implementation decision")[:500],
                    evidenceRefs=refs,
                )
            )
            continue
        if question.status == "resolved" and question.category in {"product", "fact"}:
            answer = answers.get(question.id)
            if answer and answer.text.strip() and (refs_ok or question.relatedClaimIds):
                resolutions.append(
                    QuestionResolution(
                        questionId=question.id,
                        resolutionSource="user_answer",
                        revisionId=revision.revisionId if revision is not None else revision_id,
                        answerRevisionId=answer.answerRevisionId or (revision.revisionId if revision else revision_id),
                        targetDigest=td,
                        disposition="resolved",
                        resolutionSummary=(question.reason or answer.text)[:500],
                        evidenceRefs=refs,
                    )
                )
                continue
            _keep_open(question, "answered" if answer and answer.text.strip() else "open")
            continue
        open_questions.append(question)

    blocking_open = [
        q for q in open_questions
        if q.kind in {"blocking", "choice"} and q.status not in {"resolved"}
    ]
    needs_closing = bool(blocking_open) or bool(violations)
    return ConvergenceResult(
        resolutions=resolutions,
        openQuestions=open_questions,
        violations=violations,
        needsClosingPass=needs_closing,
        analysisIncomplete=bool(violations) or bool(blocking_open),
    )
