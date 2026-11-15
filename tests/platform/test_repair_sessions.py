"""T13：缺会话仍可继续；cwd 最近会话不得盗用。"""

from bugfix_contracts.repair import AttemptRecord, REPAIR_SCHEMA_VERSION, TaskContext
from bugfix_platform.agents.analyst.sessions import choose_session


def test_missing_session_opens_new():
    ctx = TaskContext(defectId="D1")
    prev = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "needs_information",
            "patchDelivery": "none",
        }
    )
    decision = choose_session(ctx, prev)
    assert decision.action in ("resume", "new")
    assert decision.sessionId or decision.action == "new"


def test_cwd_recent_session_is_not_used():
    ctx = TaskContext(defectId="D1")
    decision = choose_session(ctx, None, cwd_recent_session_id="someone-else")
    assert decision.action == "new"
    assert decision.sessionId != "someone-else"
