"""文件反馈导入与旧补丁状态判断。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bugfix_contracts.repair import Feedback, InputRevision, PatchSet, WorkspaceSnapshot


def import_feedback(root: Path, feedback: Feedback) -> InputRevision:
    """按 feedbackId 幂等；相同文字不同 ID 仍是新一轮。"""
    base = Path(root) / "defects" / feedback.defectId / "feedback"
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"{feedback.feedbackId}.json"
    if dest.is_file():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        return InputRevision.model_validate(existing["revision"])
    revision = InputRevision(
        revisionId=f"{feedback.defectId}:{feedback.feedbackId}",
        defectId=feedback.defectId,
        parentId=feedback.attemptId,
        observed=feedback.text,
        source="feedback",
        attachments=list(feedback.attachments or []),
    )
    dest.write_text(
        json.dumps(
            {"feedback": feedback.model_dump(), "revision": revision.model_dump()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
