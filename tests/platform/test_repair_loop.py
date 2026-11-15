"""T07：隐藏错误不能当合格候选；基线已通过的测试不算修复证据。"""

from __future__ import annotations

from bugfix_contracts.repair import EditDecision, Evidence, TaskContext, VerificationRun
from bugfix_platform.agents.analyst.loop import run_ticket, semantic_review


def _ctx() -> TaskContext:
    return TaskContext(
        defectId="D1",
        generatePatch=True,
        evidence=[
            Evidence(
                evidenceId="e1",
                category="code_observation",
                summary="read src/a.ts",
                path="src/a.ts",
                validity="valid",
            )
        ],
    )


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


def test_empty_diff_is_not_candidate():
    ctx = _ctx()

    def analyze(_context):
        return EditDecision(
            behaviorTarget="btn",
            codeAssociation="src/a.ts",
            mechanism="null check missing",
            editRationale="guard",
            evidenceRefs=["e1"],
            allowed=True,
        )

    record = run_ticket(
        ctx,
        {
            "analyze": analyze,
            "edit": lambda *_a, **_k: "",
            "check": lambda *_a, **_k: VerificationRun(
                command=["pytest"], result="passed", exitCode=0
            ),
        },
    )
    assert record.patchDelivery != "candidate"
    assert record.resolution != "patch_produced"


def test_failed_check_retries_up_to_three_times():
    ctx = _ctx()
    calls = {"edit": 0, "check": 0}

    def analyze(_context):
        return EditDecision(
            behaviorTarget="btn",
            codeAssociation="src/a.ts",
            mechanism="null check missing",
            editRationale="guard",
            evidenceRefs=["e1"],
            allowed=True,
        )

    def edit(_context, _decision):
        calls["edit"] += 1
        return "diff --git a/src/a.ts b/src/a.ts\n+return x;\n"

    def check(_context, _decision, *_rest):
        calls["check"] += 1
        return VerificationRun(command=["pytest"], result="failed", exitCode=1)

    record = run_ticket(ctx, {"analyze": analyze, "edit": edit, "check": check})
    assert calls["edit"] == 3
    assert calls["check"] == 3
    assert record.patchDelivery != "candidate"
    assert record.checks and record.checks[-1].result == "failed"


def test_check_fail_then_pass_is_candidate():
    ctx = _ctx()
    calls = {"edit": 0}

    def analyze(_context):
        return EditDecision(
            behaviorTarget="btn",
            codeAssociation="src/a.ts",
            mechanism="null check missing",
            editRationale="guard",
            evidenceRefs=["e1"],
            allowed=True,
        )

    def edit(_context, _decision):
        calls["edit"] += 1
        return "diff --git a/src/a.ts b/src/a.ts\n+return x;\n"

    def check(_context, _decision, *_rest):
        result = "failed" if calls["edit"] == 1 else "passed"
        return VerificationRun(
            command=["pytest"], result=result, exitCode=0 if result == "passed" else 1
        )

    record = run_ticket(ctx, {"analyze": analyze, "edit": edit, "check": check})
    assert calls["edit"] == 2
    assert record.resolution == "patch_produced"
    assert record.patchDelivery == "candidate"


def test_failed_check_is_visible_on_next_edit():
    ctx = _ctx()
    seen: list[str] = []

    def analyze(_context):
        return EditDecision(
            behaviorTarget="btn",
            codeAssociation="src/a.ts",
            mechanism="null check missing",
            editRationale="guard",
            evidenceRefs=["e1"],
            allowed=True,
        )

    def edit(context, _decision):
        seen.append(" ".join(h.claim for h in context.hypotheses))
        return "diff --git a/src/a.ts b/src/a.ts\n+return x;\n"

    def check(_context, _decision, *_rest):
        result = "failed" if len(seen) == 1 else "passed"
        return VerificationRun(
            command=["pytest"],
            result=result,
            exitCode=0 if result == "passed" else 1,
            coverage="unit",
            logRef="assertion failed on camera path",
        )

    record = run_ticket(ctx, {"analyze": analyze, "edit": edit, "check": check})
    assert len(seen) == 2
    assert "fail" in seen[1].lower() or "camera" in seen[1].lower()
    assert record.resolution == "patch_produced"


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
