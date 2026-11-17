"""T10：固定分母，pending 不能当失败，也不能删票抬高成功率。"""

from bugfix_platform.agents.analyst.baseline import convergence_metrics


def _case(i, *, accepted=None, resolved=None, status=None, **extra):
    row = {"defectId": f"D{i}", "accepted": accepted, "resolved": resolved, "applyFix": False}
    if status:
        row["status"] = status
    row.update(extra)
    return row


def test_fixed_denominator_conservative_and_observed():
    cases = (
        [_case(i, accepted=True, resolved=True) for i in range(14)]
        + [_case(i, accepted=True, resolved=False) for i in range(14, 17)]
        + [_case(i, accepted=None, status="pending") for i in range(17, 20)]
    )
    metrics = convergence_metrics(cases)
    assert metrics["uniqueDefects"] == 20
    assert metrics["conservativeRate"] == 14 / 20
    assert metrics["observedRate"] == 14 / 17
    assert metrics["pending"] == 3
    assert metrics["repairRate"] is None
    dropped = [c for c in cases if c.get("status") != "pending"]
    dropped_metrics = convergence_metrics(dropped)
    assert dropped_metrics["uniqueDefects"] == 17
    assert dropped_metrics["conservativeRate"] != metrics["conservativeRate"]


def test_duplicate_attempts_and_stale_scores_and_zero_denominator():
    cases = [
        _case(1, accepted=True, resolved=False, attemptSeq=1),
        _case(1, accepted=True, resolved=True, attemptSeq=2),
        _case(2, accepted=True, resolved=True, ratingStatus="stale", attemptSeq=2),
        _case(2, accepted=True, resolved=False, attemptSeq=1),
    ]
    metrics = convergence_metrics(cases)
    assert metrics["uniqueDefects"] == 2
    empty = convergence_metrics([])
    assert empty["conservativeRate"] is None
    assert empty["answerConsumption"] is None
    answers = [
        _case(1, requiredQuestion=True, answerConsumed=True),
        _case(2, requiredQuestion=True, answerConsumed=False),
    ]
    assert convergence_metrics(answers)["answerConsumption"] == 0.5


def test_stale_does_not_count_as_success_and_report_only_has_no_repair_rate():
    stale_only = [_case(1, accepted=True, resolved=True, ratingStatus="stale")]
    metrics = convergence_metrics(stale_only, apply_fix=False)
    assert metrics["uniqueDefects"] == 1
    assert metrics["success"] == 0
    assert metrics["repairRate"] is None
    template = [
        _case(1, requiredQuestions=["q1"], answersConsumed=1, accepted=True, resolved=True),
    ]
    assert convergence_metrics(template)["answerConsumption"] == 1.0
