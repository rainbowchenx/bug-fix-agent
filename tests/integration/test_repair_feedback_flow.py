"""T14：缺信息补足 / 拒绝候选 / 应用后追加 的最小闭环。"""

from pathlib import Path

from bugfix_contracts.repair import (
    REPAIR_SCHEMA_VERSION,
    AttemptRecord,
    Feedback,
    PatchFile,
    PatchSet,
    TaskContext,
    WorkspaceSnapshot,
)
from bugfix_platform.agents.analyst.attempt_store import save_attempt
from bugfix_platform.agents.analyst.feedback import classify_patch_state, import_feedback
from bugfix_platform.agents.analyst.sessions import choose_session


def test_needs_info_then_supplement(tmp_path: Path):
    root = tmp_path / "art"
    first = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "needs_information",
            "patchDelivery": "none",
        }
    )
    save_attempt(root, first)
    rev = import_feedback(
        root,
        Feedback.model_validate(
            {
                "feedbackId": "f1",
                "defectId": "D1",
                "attemptId": "a1",
                "application": "not_applied",
                "acceptance": "rejected",
                "text": "补充：失败消息是 camera_disconnected",
            }
        ),
    )
    decision = choose_session(TaskContext(defectId="D1", revision=rev), first)
    assert "camera_disconnected" in rev.feedbackText
    assert decision.action in ("resume", "new")


def test_rejected_candidate_is_not_success(tmp_path: Path):
    root = tmp_path / "art"
    patch = PatchSet(
        patchSetId="p1",
        delivery="candidate",
        baselineHead="abc",
        patches=[
            PatchFile(path="src/a.ts", kind="modify", digest="d1", archivePath="p1/a.ts")
        ],
    )
    first = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "patch_produced",
            "patchDelivery": "candidate",
            "patchSet": patch.model_dump(),
        }
    )
    save_attempt(root, first)
    rev = import_feedback(
        root,
        Feedback.model_validate(
            {
                "feedbackId": "f-rej",
                "defectId": "D1",
                "attemptId": "a1",
                "patchSetId": "p1",
                "application": "not_applied",
                "acceptance": "rejected",
                "text": "仍未解决，坐标还是错",
            }
        ),
    )
    state = classify_patch_state(
        patch,
        WorkspaceSnapshot(repoId=".", head="abc", dirty=[], untracked=[]),
    )
    assert rev.source == "feedback"
    assert state["application"] in ("unknown", "not_applied")
    assert first.userAcceptance != "accepted"


def test_applied_then_followup_feedback(tmp_path: Path):
    root = tmp_path / "art"
    first = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "patch_produced",
            "patchDelivery": "candidate",
        }
    )
    save_attempt(root, first)
    first_fb = import_feedback(
        root,
        Feedback.model_validate(
            {
                "feedbackId": "f-ok",
                "defectId": "D1",
                "attemptId": "a1",
                "application": "applied",
                "acceptance": "partially_resolved",
                "text": "主路径好了，重试仍失败",
            }
        ),
    )
    second_fb = import_feedback(
        root,
        Feedback.model_validate(
            {
                "feedbackId": "f-more",
                "defectId": "D1",
                "attemptId": "a1",
                "application": "applied",
                "acceptance": "rejected",
                "text": "重试按钮仍无响应",
            }
        ),
    )
    assert first_fb.revisionId != second_fb.revisionId
    decision = choose_session(TaskContext(defectId="D1", revision=second_fb), first)
    assert decision.action in ("resume", "new", "fork")
