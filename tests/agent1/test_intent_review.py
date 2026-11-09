"""Intent-review overrides after the rule pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bugfix_agent1.cli import main as cli_main
from bugfix_contracts.defect_batch import BatchTicket, DefectBatch
from bugfix_agent1.defect_batch.review import IntentOverride, apply_intent_review


def _ticket(**kwargs) -> BatchTicket:
    data = {
        "defectId": "D1",
        "title": "【登录】按钮偏移",
        "pool": "strict",
        "clusterId": "hc::login::_untagged::unclear",
        "testModule": "login",
        "titleTag": "_untagged",
        "intent": "unclear",
        "intentSource": "heuristic",
        "intentConfidence": "low",
        "intentRationale": "no strong intent signal",
        "expectQuality": "inferred",
        "observed": "按钮偏了",
        "expected": "对齐",
        "status": "Open",
    }
    data.update(kwargs)
    return BatchTicket.model_validate(data)


def _batch(*tickets: BatchTicket) -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-11-05T00:00:00Z",
            "funnel": {"total": len(tickets)},
            "clusters": [],
            "tickets": [t.model_dump() for t in tickets],
        }
    )


def test_intent_override_rebuilds_cluster_id():
    batch = _batch(_ticket())
    out = apply_intent_review(
        batch,
        [IntentOverride(defectId="D1", intent="ui_layout", intentRationale="标题+实际都是布局偏移")],
    )
    ticket = out.tickets[0]
    assert ticket.intent == "ui_layout"
    assert ticket.intentSource == "ai"
    assert ticket.intentConfidence == "high"
    assert ticket.clusterId is not None
    assert ticket.clusterId.startswith("hc::login::_untagged::ui_layout")
    assert out.clusters[0].intent == "ui_layout"
    assert out.clusters[0].defectIds == ["D1"]
    assert out.funnel["strict"] == 1


def test_promote_needs_info_into_strict():
    batch = _batch(
        _ticket(
            pool="needs_info",
            clusterId=None,
            intent=None,
            intentSource=None,
            expectQuality="absent",
            reasonCode="C1",
        )
    )
    out = apply_intent_review(
        batch,
        [
            {
                "defectId": "D1",
                "pool": "strict",
                "expectQuality": "inferred",
                "intent": "logic",
                "intentRationale": "原文能读出应保存失败提示",
            }
        ],
    )
    ticket = out.tickets[0]
    assert ticket.pool == "strict"
    assert ticket.intent == "logic"
    assert ticket.clusterId is not None
    assert ticket.clusterId.startswith("hc::login::_untagged::logic")
    assert out.funnel["strict"] == 1
    assert out.funnel["needs_info"] == 0


def test_reject_protected_pool_override():
    batch = _batch(_ticket(pool="security", clusterId=None, intent=None))
    with pytest.raises(ValueError, match="protected pool"):
        apply_intent_review(batch, [IntentOverride(defectId="D1", intent="ui_layout")])


def test_strict_requires_expect_quality():
    batch = _batch(
        _ticket(
            pool="locatable_only",
            clusterId=None,
            expectQuality="ambiguous",
        )
    )
    with pytest.raises(ValueError, match="expectQuality"):
        apply_intent_review(batch, [IntentOverride(defectId="D1", pool="strict")])


def test_locatable_keeps_intent_without_cluster():
    batch = _batch(
        _ticket(pool="locatable_only", clusterId=None, intent=None, expectQuality="ambiguous")
    )
    out = apply_intent_review(batch, [IntentOverride(defectId="D1", intent="i18n")])
    ticket = out.tickets[0]
    assert ticket.pool == "locatable_only"
    assert ticket.intent == "i18n"
    assert ticket.intentSource == "ai"
    assert ticket.clusterId is None
    assert out.clusters == []


def test_unknown_defect_id():
    batch = _batch(_ticket())
    with pytest.raises(ValueError, match="unknown defectId"):
        apply_intent_review(batch, [IntentOverride(defectId="NOPE", intent="logic")])


def test_empty_adjustment_rejected():
    with pytest.raises(ValidationError):
        IntentOverride(defectId="D1")


def test_cli_apply_review(tmp_path: Path):
    batch_path = tmp_path / "defect-batch.json"
    overrides_path = tmp_path / "review.json"
    out_path = tmp_path / "out.json"
    batch_path.write_text(_batch(_ticket()).model_dump_json(), encoding="utf-8")
    overrides_path.write_text(
        json.dumps(
            {
                "adjustments": [
                    {
                        "defectId": "D1",
                        "intent": "ui_layout",
                        "intentRationale": "布局偏移",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code = cli_main(
        [
            "apply-review",
            "--batch",
            str(batch_path),
            "--overrides",
            str(overrides_path),
            "--out",
            str(out_path),
        ]
    )
    assert code == 0
    dumped = json.loads(out_path.read_text(encoding="utf-8"))
    assert dumped["tickets"][0]["intent"] == "ui_layout"
    assert dumped["tickets"][0]["intentSource"] == "ai"
