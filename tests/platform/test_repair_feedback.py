"""T11：同 ID 不建两轮；相同文字不同 ID 保留。"""

from pathlib import Path

from bugfix_contracts.repair import Feedback
from bugfix_platform.agents.analyst.feedback import import_feedback


def test_feedback_idempotent_and_distinct_ids(tmp_path: Path):
    root = tmp_path / "art"
    fb = Feedback.model_validate(
        {
            "feedbackId": "f1",
            "defectId": "D1",
            "attemptId": "a1",
            "application": "not_applied",
            "acceptance": "rejected",
            "text": "仍未解决",
        }
    )
    r1 = import_feedback(root, fb)
    r2 = import_feedback(root, fb)
    assert r1.revisionId == r2.revisionId
    other = Feedback.model_validate(
        {
            "feedbackId": "f2",
            "defectId": "D1",
            "attemptId": "a1",
            "application": "not_applied",
            "acceptance": "rejected",
            "text": "仍未解决",
        }
    )
    r3 = import_feedback(root, other)
    assert r3.revisionId != r1.revisionId
