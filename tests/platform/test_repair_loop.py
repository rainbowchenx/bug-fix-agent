"""T07：隐藏错误不能当合格候选；基线已通过的测试不算修复证据。"""

from __future__ import annotations

from bugfix_contracts.repair import EditDecision, TaskContext, VerificationRun
from bugfix_platform.agents.analyst.loop import run_ticket, semantic_review


def test_hiding_error_or_deleting_assert_is_not_candidate():
    issues = semantic_review(
        "diff --git a/src/a.ts b/src/a.ts\n"
        "+try { foo() } catch (e) {}\n"
        "-expect(el.text).toBe('ok')\n",
        TaskContext(defectId="D1"),
        EditDecision(allowed=True, mechanism="x"),
    )
    assert issues


def test_baseline_already_passing_is_not_repair_evidence():
    check = VerificationRun.model_validate(
        {
            "command": ["pytest", "tests/test_foo.py"],
            "cwd": "work",
            "result": "passed",
            "exitCode": 0,
            "coverage": "baseline_already_passed",
        }
    )
    assert check.coverage != "defect_fix_evidence"


def test_run_ticket_uses_injected_services(tmp_path):
    ctx = TaskContext(defectId="D1", generatePatch=False)
    calls = {"n": 0}

    def analyze(context):
        calls["n"] += 1
        return EditDecision(
            behaviorTarget="t",
            codeAssociation="src/a.ts",
            mechanism="m",
            editRationale="r",
            evidenceRefs=["e1"],
            allowed=False,
            reason="need more logs",
        )

    record = run_ticket(
        ctx,
        {
            "analyze": analyze,
            "edit": lambda *a, **k: None,
            "check": lambda *a, **k: None,
            "save": lambda *a, **k: None,
        },
    )
    assert calls["n"] == 1
    assert record.resolution != "patch_produced"
    assert record.schemaVersion
