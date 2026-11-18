"""Feedback import and single-defect continuation for formal entry points."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from bugfix_contracts.analysis_report import AnalysisReport
from bugfix_contracts.repair import InputRevision
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
) -> AnalysisReport | None:
    with store_lock(root):
        return _resume_locked(root, defect_id, revision_id, apply_fix, execute, on_decision)


def import_run_feedback(root: Path, source: Path) -> InputRevision:
    """导入一份反馈 JSON 或填写后的 Markdown 表，按 feedbackId 幂等。"""
    from bugfix_contracts.repair import Feedback
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from bugfix_platform.agents.analyst.feedback_document import import_filled_form

    src = source
    text = src.read_text(encoding="utf-8")
    with store_lock(Path(root)):
        if src.suffix.lower() in {".md", ".markdown"} or "BUGFIX_FEEDBACK_FORM" in text:
            revision = import_filled_form(root, text, already_locked=True)
        else:
            feedback = Feedback.model_validate(json.loads(text))
            revision = import_feedback(Path(root), feedback, already_locked=True)
    return revision


def _resume_locked(
    base: Path, defect_id: str, revision_id: str | None, apply_fix: bool, execute: bool,
    on_decision: Callable[[SessionDecision], None] | None,
) -> AnalysisReport | None:
    """预览会话决策；execute 只分析，apply-fix 显式授权编辑。"""
    from bugfix_contracts.code_knowledge import validate_code_knowledge
    from bugfix_contracts.defect_batch import load_defect_batch
    from bugfix_platform.agents.analyst.report_store import (
        load_or_rebuild_analysis_report, merge_analysis_report, publish_analysis_report,
    )
    from bugfix_platform.agents.analyst.run import run_analyst
    from bugfix_platform.agents.analyst.sessions import load_revision, resume_from_store

    batch_path = base / "defect-batch.json"
    knowledge_path = base / "code-knowledge.json"
    report_path = base / "analysis-report.json"
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
    decision = resume_from_store(base, defect_id, revision_id)
    if on_decision is not None:
        on_decision(decision)
    if not apply_fix and not execute:
        return None
    assert knowledge is not None
    work_dir = previous.workDir if previous is not None else knowledge.workDir
    revision = load_revision(base, defect_id, revision_id)
    revisions = {defect_id: revision} if revision is not None else {}
    session_ids = {defect_id: decision.sessionId} if decision.sessionId else {}
    from bugfix_platform.agents.analyst.feedback import load_latest_feedback
    from bugfix_platform.agents.analyst.sessions import load_latest_attempt, select_resume_parent
    feedback = load_latest_feedback(base, defect_id)
    latest = load_latest_attempt(base, defect_id)
    parent_id = select_resume_parent(latest, feedback, revision_id=revision_id)
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
