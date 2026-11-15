"""T02：TaskContext 保留原文、附件未读不得杜撰。"""

from __future__ import annotations

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.agents.analyst.context import build_task_context


def _ticket(**kw) -> BatchTicket:
    data = {
        "defectId": "D1",
        "title": "激活无反馈",
        "pool": "strict",
        "expectQuality": "explicit",
        "observed": "蒸馏后的现象",
        "expected": "蒸馏后的预期",
        "steps": "蒸馏步骤",
        "sourceObserved": "原始现象全文",
        "sourceExpected": "原始预期全文",
        "sourceSteps": "原始步骤全文",
        "attachmentRefs": ["shots/fail.png"],
    }
    data.update(kw)
    return BatchTicket.model_validate(data)


def test_build_task_context_keeps_source_fields():
    ctx = build_task_context(_ticket(), knowledge=None, revision=None, snapshot=None)
    assert ctx.defectId == "D1"
    assert ctx.revision is not None
    assert ctx.revision.observed == "原始现象全文"
    assert ctx.revision.expected == "原始预期全文"
    assert ctx.revision.steps == "原始步骤全文"
    assert "shots/fail.png" in ctx.revision.attachments


def test_missing_image_is_unread_not_invented():
    ctx = build_task_context(_ticket(), knowledge=None, revision=None, snapshot=None)
    assert ctx.unreadAttachments == ["shots/fail.png"]
    assert all("臆" not in (e.summary or "") for e in ctx.evidence)
