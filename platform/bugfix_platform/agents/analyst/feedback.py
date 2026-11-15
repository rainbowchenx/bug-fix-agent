"""文件反馈导入与旧补丁状态判断。"""

from __future__ import annotations

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


def classify_patch_state(patch: PatchSet, snapshot: WorkspaceSnapshot) -> dict[str, Any]:
    """HEAD 相同但文件集合对不上 → 部分应用 / 未知，不盲目全信。"""
    paths = {p.path.replace("\\", "/") for p in patch.patches}
    dirty = {p.replace("\\", "/") for p in snapshot.dirty + snapshot.untracked}
    if snapshot.head and patch.baselineHead and snapshot.head != patch.baselineHead:
        return {
            "application": "unknown",
            "reason": "HEAD changed; re-check file contents before replay",
        }
    overlap = paths & dirty
    if overlap and overlap < paths:
        return {
            "application": "partially_applied",
            "reason": f"same HEAD, dirty subset {sorted(overlap)}",
        }
    if overlap == paths and paths:
        return {"application": "applied", "reason": "all patch paths dirty on same HEAD"}
    if not overlap:
        return {
            "application": "unknown",
            "reason": "same HEAD but patch paths not in dirty list",
        }
    return {"application": "unknown", "reason": "ambiguous patch vs workspace"}
