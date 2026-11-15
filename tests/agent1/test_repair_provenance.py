"""T02：原文保真；模板非空不等于明确验收。"""

from __future__ import annotations

from bugfix_agent1.defect_batch.distill import DefectDigest
from bugfix_agent1.defect_batch.expect_quality import classify_expect_quality


def _digest(**kw) -> DefectDigest:
    base = dict(
        defectId="D1",
        title="激活按钮置灰无反馈",
        description="原始描述全文应可追溯",
        status="open",
        flowStatus=None,
        testModuleRaw="业务安全",
        fieldType=None,
        severity=None,
        createdAt=None,
        duplicateOf=None,
        duplicate=False,
        observed="点激活后按钮置灰",
        expected="应提示成功或失败",
        steps="打开激活页",
        titleTag="_untagged",
        testModule="业务安全",
        semanticFree=False,
        fullText="激活按钮置灰无反馈\n点激活后按钮置灰",
        emptyTemplate=False,
    )
    base.update(kw)
    return DefectDigest(**base)


def test_generic_template_expected_is_not_explicit():
    d = _digest(expected="符合预期", observed="点激活后按钮置灰")
    assert classify_expect_quality(d) != "explicit"


def test_conflicting_expected_is_not_wiped():
    d = _digest(expected="应提示失败", observed="无任何提示")
    assert classify_expect_quality(d) == "explicit"
    assert d.expected == "应提示失败"
    assert d.observed == "无任何提示"


def test_clustered_ticket_keeps_source_and_attachments():
    from bugfix_agent1.defect_batch.cluster import cluster_screened
    from bugfix_agent1.defect_batch.distill import distill_defect
    from bugfix_agent1.defect_batch.screen import ScreenedTicket
    from bugfix_contracts.defect_batch import RawDefect

    raw = RawDefect.model_validate(
        {
            "defectId": "D1",
            "title": "激活按钮置灰无反馈",
            "description": (
                "实际结果：点激活后按钮置灰\n"
                "期望结果：应提示成功或失败\n"
                "操作步骤：打开激活页"
            ),
            "metadata": {"attachments": ["shots/fail.png"]},
        }
    )
    dig = distill_defect(raw)
    screened = ScreenedTicket(
        digest=dig,
        pool="strict",
        verdict="FIXABLE",
        expectQuality="explicit",
    )
    _, tickets = cluster_screened([screened], "hc")
    ticket = tickets[0]
    assert ticket.sourceObserved and "置灰" in ticket.sourceObserved
    assert ticket.sourceExpected and "提示" in ticket.sourceExpected
    assert ticket.sourceSteps and "激活页" in ticket.sourceSteps
    assert ticket.attachmentRefs == ["shots/fail.png"]
    assert ticket.revisionId == "D1:v0"
