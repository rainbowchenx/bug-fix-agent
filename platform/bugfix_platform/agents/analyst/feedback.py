"""文件反馈导入与旧补丁状态判断。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.repair import Feedback, InputRevision, PatchSet, WorkspaceSnapshot


def import_feedback(root: Path, feedback: Feedback, *, already_locked: bool = False) -> InputRevision:
    """按 feedbackId 幂等；相同文字不同 ID 仍是新一轮。"""
    from bugfix_platform.agents.analyst.attempt_store import store_lock

    def _import() -> InputRevision:
        return _import_feedback_locked(Path(root), feedback)

    if already_locked:
        return _import()
    with store_lock(Path(root)):
        return _import()


def _import_feedback_locked(root: Path, feedback: Feedback) -> InputRevision:
    batch_path = Path(root) / "defect-batch.json"
    original_ticket = None
    if batch_path.is_file():
        from bugfix_contracts.defect_batch import load_defect_batch
        batch = load_defect_batch(batch_path)
        original_ticket = next((t for t in batch.tickets if t.defectId == feedback.defectId), None)
        if original_ticket is None:
            raise ValueError(f"unknown defect: {feedback.defectId}")
    base = Path(root) / "defects" / feedback.defectId / "feedback"
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"{feedback.feedbackId}.json"
    if dest.is_file():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        stored = existing.get("feedback") or {}
        if stored.get("feedbackId") == feedback.feedbackId:
            comparable = {k: v for k, v in feedback.model_dump().items() if k != "parentRevisionId"}
            stored_cmp = {k: v for k, v in stored.items() if k != "parentRevisionId"}
            if comparable != stored_cmp and stored != feedback.model_dump():
                raise ValueError("feedbackId conflicts with existing content")
            return InputRevision.model_validate(existing["revision"])
        if stored != feedback.model_dump():
            raise ValueError("feedbackId conflicts with existing content")
        return InputRevision.model_validate(existing["revision"])
    if feedback.attemptId:
        from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot, snapshot_path
        snap = snapshot_path(root, feedback.defectId, feedback.attemptId)
        if snap.is_file() or feedback.formId:
            try:
                load_analysis_snapshot(root, feedback.defectId, feedback.attemptId)
            except OSError as err:
                raise ValueError(f"unknown parent attempt: {feedback.attemptId}") from err
    from bugfix_platform.agents.analyst.revisions import merge_revision
    parent = None
    from bugfix_platform.agents.analyst.sessions import load_revision
    try:
        parent = load_revision(root, feedback.defectId, None)
    except ValueError:
        raise
    if parent is None:
        if original_ticket is not None:
            ticket = original_ticket
            parent = InputRevision(revisionId=ticket.revisionId or f"{feedback.defectId}:v0",
                defectId=feedback.defectId, observed=ticket.observed, expected=ticket.expected,
                steps=ticket.steps, attachments=ticket.attachmentRefs or [])
    if parent is None:
        parent = InputRevision(revisionId=f"{feedback.defectId}:v0", defectId=feedback.defectId)
    merge_source = feedback.model_copy(update={"parentRevisionId": parent.revisionId})
    revision = merge_revision(parent, merge_source)
    temporary = dest.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"feedback": feedback.model_dump(), "revision": revision.model_dump()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(dest)
    pointer = base.parent / "feedback-latest.json"
    pointer_tmp = pointer.with_suffix(".tmp")
    pointer_tmp.write_text(
        json.dumps({"revisionId": revision.revisionId, "attemptId": feedback.attemptId}),
        encoding="utf-8",
    )
    pointer_tmp.replace(pointer)
    return revision


def load_latest_feedback(root: Path, defect_id: str, *, revision_id: str | None = None) -> Optional[Feedback]:
    folder = Path(root) / "defects" / defect_id / "feedback"
    if not folder.is_dir():
        return None
    pointer = folder.parent / "feedback-latest.json"
    if revision_id is None and pointer.is_file():
        revision_id = json.loads(pointer.read_text(encoding="utf-8"))["revisionId"]
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if revision_id is not None and (payload.get("revision") or {}).get("revisionId") != revision_id:
            continue
        raw = payload.get("feedback")
        if not isinstance(raw, dict):
            continue
        try:
            feedback = Feedback.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        if feedback.defectId == defect_id:
            return feedback
    return None


def classify_patch_state(
    patch: PatchSet,
    snapshot: WorkspaceSnapshot,
    worktree: Path | None = None,
) -> dict[str, Any]:
    """比较当前文件内容与补丁后镜像。无法确认则 unknown，不用 dirty 冒充已应用。"""
    if snapshot.head and patch.baselineHead and snapshot.head != patch.baselineHead:
        return {
            "application": "unknown",
            "reason": "HEAD changed; re-check file contents before replay",
        }
    if worktree is None:
        return {
            "application": "unknown",
            "reason": "no current files to compare",
        }
    work = Path(worktree)
    marks: list[str] = []
    for item in patch.patches:
        current = work / item.path
        data = current.read_bytes() if current.is_file() else b""
        digest = hashlib.sha256(data).hexdigest()[:16]
        if item.digest and digest == item.digest[:16]:
            marks.append("applied")
        else:
            marks.append("mismatch")
    if marks and all(m == "applied" for m in marks):
        return {"application": "applied", "reason": "current content matches patch digest"}
    if marks and any(m == "applied" for m in marks):
        return {
            "application": "partially_applied",
            "reason": "some patch paths match digest, others do not",
        }
    return {
        "application": "unknown",
        "reason": "current content does not match patch; unrelated edits possible",
    }
