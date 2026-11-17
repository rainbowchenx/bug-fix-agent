"""文件反馈导入与旧补丁状态判断。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bugfix_contracts.repair import Feedback, InputRevision, PatchSet, WorkspaceSnapshot


def import_feedback(root: Path, feedback: Feedback) -> InputRevision:
    """按 feedbackId 幂等；相同文字不同 ID 仍是新一轮。"""
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
        if existing.get("feedback") != feedback.model_dump():
            raise ValueError("feedbackId conflicts with existing content")
        return InputRevision.model_validate(existing["revision"])
    from bugfix_platform.agents.analyst.revisions import merge_revision
    parent = None
    from bugfix_platform.agents.analyst.sessions import load_revision
    try:
        parent = load_revision(root, feedback.defectId, feedback.parentRevisionId)
    except ValueError:
        if not feedback.parentRevisionId:
            raise
        parent = None  # An explicitly requested original ticket revision is resolved below.
    if parent is None:
        if original_ticket is not None:
            ticket = original_ticket
            parent = InputRevision(revisionId=ticket.revisionId or f"{feedback.defectId}:v0",
                defectId=feedback.defectId, observed=ticket.observed, expected=ticket.expected,
                steps=ticket.steps, attachments=ticket.attachmentRefs or [])
    if parent is None:
        if feedback.parentRevisionId:
            raise ValueError("unknown parent revision")
        parent = InputRevision(revisionId=f"{feedback.defectId}:v0", defectId=feedback.defectId)
    revision = merge_revision(parent, feedback)
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
    pointer_tmp.write_text(json.dumps({"revisionId": revision.revisionId}), encoding="utf-8")
    pointer_tmp.replace(pointer)
    return revision


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
