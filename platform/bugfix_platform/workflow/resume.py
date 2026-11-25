"""Feedback import and single-defect continuation for formal entry points."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable, Sequence

from bugfix_contracts.analysis_report import AnalysisReport
from bugfix_contracts.repair import InputRevision, TaskContext
from bugfix_platform.agents.analyst.attempt_store import AttemptStoreBusy, store_lock
from bugfix_platform.agents.analyst.sessions import SessionDecision


class ResumeRequestError(ValueError):
    """The requested continuation cannot run with the supplied artifacts."""


def resume_defect(
    root: Path,
    defect_id: str,
    revision_id: str | None = None,
    *,
    execute: bool = False,
    apply_fix: bool = False,
    on_decision: Callable[[SessionDecision], None] | None = None,
    agent3_mcp_tools: Sequence[str] = (),
    feedback_file: Path | None = None,
    repair_skill_path: str | Path | None = None,
    project_integrations: bool = False,
    analyze_mode: str | None = None,
) -> AnalysisReport | None:
    _require_file_id(defect_id)
    if feedback_file is not None and (revision_id is not None or not (execute or apply_fix)):
        raise ResumeRequestError("feedback_file requires execution and cannot be combined with revision_id")
    with store_lock(root):
        return _resume_locked(
            root, defect_id, revision_id, apply_fix, execute, on_decision, agent3_mcp_tools,
            feedback_file, repair_skill_path, project_integrations, analyze_mode,
        )


def import_run_feedback(root: Path, source: Path) -> InputRevision:
    """导入一份反馈 JSON 或填写后的 Markdown 表，按 feedbackId 幂等。"""
    with store_lock(Path(root)):
        return _import_feedback_file(root, source)


def _require_file_id(value: str) -> None:
    if not value or value in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ResumeRequestError(f"Invalid artifact identifier: {value!r}")


def _import_feedback_file(
    root: Path, source: Path, *, defect_id: str | None = None, attempt_id: str | None = None,
) -> InputRevision:
    from bugfix_contracts.repair import Feedback
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from bugfix_platform.agents.analyst.feedback_document import archive_feedback_form, parse_feedback_form

    text = source.read_text(encoding="utf-8-sig")
    form = source.suffix.lower() in {".md", ".markdown"} or "BUGFIX_FEEDBACK_FORM" in text
    feedback = parse_feedback_form(text, store=root) if form else Feedback.model_validate(json.loads(text))
    _require_file_id(feedback.defectId)
    _require_file_id(feedback.feedbackId)
    if defect_id is not None and feedback.defectId != defect_id:
        raise ResumeRequestError(f"feedback defectId {feedback.defectId!r} does not match {defect_id!r}")
    if feedback.attemptId:
        _require_file_id(feedback.attemptId)
        if attempt_id is not None and feedback.attemptId != attempt_id:
            raise ResumeRequestError(f"stale feedback for attempt {feedback.attemptId}; current attempt: {attempt_id}")
    if attempt_id is not None and not feedback.attemptId:
        feedback = feedback.model_copy(update={"attemptId": attempt_id})
    revision = import_feedback(Path(root), feedback, already_locked=True)
    if form:
        archive_feedback_form(root, feedback, text)
    return revision


def _resume_locked(
    base: Path, defect_id: str, revision_id: str | None, apply_fix: bool, execute: bool,
    on_decision: Callable[[SessionDecision], None] | None,
    agent3_mcp_tools: Sequence[str],
    feedback_file: Path | None,
    repair_skill_path: str | Path | None,
    project_integrations: bool,
    analyze_mode: str | None,
) -> AnalysisReport | None:
    """预览会话决策；execute 只分析，apply-fix 显式授权编辑。"""
    from bugfix_contracts.code_knowledge import validate_code_knowledge
    from bugfix_contracts.defect_batch import load_defect_batch
    from bugfix_platform.agents.analyst.report_store import (
        load_or_rebuild_analysis_report, merge_analysis_report, publish_analysis_report,
    )
    from bugfix_platform.agents.analyst.run import run_analyst
    from bugfix_platform.agents.analyst.feedback import load_latest_feedback
    from bugfix_platform.agents.analyst.sessions import (
        choose_session, load_latest_attempt, load_revision, resume_from_store, write_session_decision,
    )

    batch_path = base / "defect-batch.json"
    knowledge_path = base / "code-knowledge.json"
    batch = load_defect_batch(batch_path) if batch_path.is_file() else None
    if batch is not None and not any(t.defectId == defect_id for t in batch.tickets):
        raise ResumeRequestError(f"unknown defect: {defect_id}")
    previous = None
    knowledge = None
    if apply_fix or execute:
        if batch is None or not knowledge_path.is_file():
            raise ResumeRequestError("resume execution needs defect-batch.json and code-knowledge.json")
        knowledge = validate_code_knowledge(json.loads(knowledge_path.read_text(encoding="utf-8")))
        previous = load_or_rebuild_analysis_report(
            base,
            product_line=batch.productLine,
            work_dir=knowledge.workDir,
            apply_fix=apply_fix,
        )
    if not apply_fix and not execute:
        decision = resume_from_store(base, defect_id, revision_id)
        if on_decision is not None:
            on_decision(decision)
        return None
    assert knowledge is not None
    work_dir = previous.workDir if previous is not None else knowledge.workDir
    latest = load_latest_attempt(base, defect_id)
    if latest is None and (base / "defects" / defect_id / "latest.json").exists():
        raise ResumeRequestError(f"cannot read latest attempt for {defect_id}")
    parent_id = latest.attemptId if latest else None
    if feedback_file is not None:
        if parent_id is None:
            raise ResumeRequestError(f"no initial Agent3 attempt to attach feedback for {defect_id}")
        revision = _import_feedback_file(base, feedback_file, defect_id=defect_id, attempt_id=parent_id)
    else:
        revision = load_revision(base, defect_id)
    current_id = revision.revisionId if revision is not None else None
    if revision_id is not None and revision_id != current_id:
        raise ResumeRequestError(f"stale or unknown revision {revision_id}; current revision: {current_id or 'none'}")
    if current_id is not None:
        feedback = load_latest_feedback(base, defect_id, revision_id=current_id)
        if feedback is None:
            raise ResumeRequestError(f"cannot read feedback for revision {current_id}")
        already_used = latest is not None and latest.revisionId == current_id
        if feedback.attemptId and feedback.attemptId != parent_id and not already_used:
            raise ResumeRequestError(f"stale feedback for attempt {feedback.attemptId}; current attempt: {parent_id or 'none'}")
    decision = choose_session(TaskContext(defectId=defect_id, revision=revision), latest)
    write_session_decision(base, defect_id, decision)
    if on_decision is not None:
        on_decision(decision)
    revisions = {defect_id: revision} if revision is not None else {}
    session_ids = {defect_id: decision.sessionId} if decision.sessionId else {}
    parent_attempt_ids = {defect_id: parent_id} if parent_id else {}
    report = run_analyst(
        work_dir=work_dir,
        defect_batch=batch,
        code_knowledge=knowledge,
        apply_fix=apply_fix,
        ticket_ids=[defect_id],
        revisions=revisions,
        session_ids=session_ids,
        parent_attempt_ids=parent_attempt_ids,
        artifact_dir=base,
        already_locked=True,
        agent3_mcp_tools=agent3_mcp_tools,
        repair_skill_path=repair_skill_path,
        project_integrations=project_integrations,
        analyze_mode=analyze_mode,
    )
    dumped = report.model_dump()
    round_dir = base / "rounds"
    round_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (round_dir / f"{defect_id}-{stamp}.json").write_text(
        json.dumps(dumped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    merged = merge_analysis_report(report, previous)
    publish_analysis_report(base, merged, already_locked=True)
    return merged
