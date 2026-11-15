"""T00：修复闭环基线 — 现有失败先归因，无验收数据不打成功率。"""

from __future__ import annotations

from pathlib import Path

from bugfix_platform.agents.analyst.baseline import (
    REPAIR_CASE_KINDS,
    attribute_test_failures,
    collect_repair_baseline,
    repair_success_metrics,
)

ROOT = Path(__file__).resolve().parents[2]
CASES_README = ROOT / "tests" / "platform" / "repair_cases" / "README.md"


def test_preexisting_failures_are_attributed_before_new():
    """现有环境缺口（缺 SDK）先记为 preexisting，不能当成新回归。"""
    failed = [
        "tests/platform/test_sdk_billing.py::test_success_records_billing_in_artifact",
        "tests/platform/test_repair_loop.py::test_hides_error_is_not_candidate",
    ]
    split = attribute_test_failures(failed)
    assert any("test_sdk_billing" in n for n in split["preexisting"])
    assert any("test_repair_loop" in n for n in split["new"])
    assert split["preexisting"] and split["new"]


def test_no_acceptance_data_does_not_emit_success_rate():
    metrics = repair_success_metrics(accepted=0, resolved=0, reported=12)
    assert metrics["successRate"] is None
    assert metrics["reason"] == "no_acceptance_data"
    assert "12" in str(metrics["denominator"]) or metrics["reported"] == 12


def test_repair_cases_readme_lists_four_fixture_kinds():
    text = CASES_README.read_text(encoding="utf-8")
    for kind in REPAIR_CASE_KINDS:
        assert kind in text, kind
    assert len(REPAIR_CASE_KINDS) == 4


def test_collect_repair_baseline_records_python_and_schema():
    baseline = collect_repair_baseline(ROOT)
    assert baseline["python"]
    assert baseline["schemaVersion"]
    assert "gitHead" in baseline
    assert "limits" in baseline
    for kind in REPAIR_CASE_KINDS:
        assert kind in baseline["fixtureKinds"]
