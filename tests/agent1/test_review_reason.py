"""复核改池后，筛因必须跟着失效。

``reasonCode`` / ``reasonDetail`` 回答的是「为什么没进 strict」。票一旦升进 strict，
旧答案就过期了：它会经 ``slice_ticket`` 原样进 AnalysisReport，让交付物自相矛盾
（pool=strict 却写着「报错无细节，信息不足」）。
"""

from __future__ import annotations

import pytest

from bugfix_agent1.defect_batch.review import apply_intent_review
from bugfix_contracts.defect_batch import validate_defect_batch


def _batch(pool: str, reason_code: str | None, reason_detail: str | None) -> dict:
    return {
        "schemaVersion": "0.1.0",
        "productLine": "PJ01PM20260711040",
        "posture": "beta",
        "generatedAt": "2026-11-10T00:00:00Z",
        "funnel": {
            "total": 1,
            "strict": 1 if pool == "strict" else 0,
            "locatable_only": 1 if pool == "locatable_only" else 0,
            "needs_info": 1 if pool == "needs_info" else 0,
            "hard_reject": 0,
            "security": 0,
            "excluded": 0,
            "duplicate": 0,
        },
        "clusters": [],
        "tickets": [
            {
                "defectId": "BGCM2026110304491",
                "title": "[双频电警RFID] 外场设备RFID标签查询报错",
                "pool": pool,
                "testModule": "双频电警RFID",
                "titleTag": "双频电警RFID",
                "intent": "logic" if pool == "strict" else None,
                "intentSource": "heuristic" if pool == "strict" else None,
                "intentConfidence": "low" if pool == "strict" else None,
                "intentRationale": "x" if pool == "strict" else None,
                "fieldType": "缺陷",
                "expectQuality": "explicit",
                "reasonCode": reason_code,
                "reasonDetail": reason_detail,
                "observed": "RFID标签查询报错",
                "expected": "1.查询成功",
                "steps": "",
                "status": "Open",
                "severity": "中",
                "createdAt": "2026-11-10 00:00:00",
                "duplicate": False,
                "semanticFree": False,
                "priority": 0.0 if pool == "strict" else None,
            }
        ],
    }


def test_promotion_clears_stale_reason():
    batch = validate_defect_batch(_batch("needs_info", "C1e", "error mentioned without detail"))
    out = apply_intent_review(
        batch,
        [
            {
                "defectId": "BGCM2026110304491",
                "intent": "logic",
                "intentConfidence": "medium",
                "intentRationale": "原文有前置/步骤/预期，按定义不属于信息缺口",
                "pool": "strict",
                "expectQuality": "explicit",
            }
        ],
    )
    ticket = out.tickets[0]
    assert ticket.pool == "strict"
    assert ticket.reasonCode is None
    assert ticket.reasonDetail is None
    assert out.clusters, "升进 strict 后应该落进簇"


def test_demotion_clears_reason_too():
    batch = validate_defect_batch(_batch("strict", None, None))
    out = apply_intent_review(batch, [{"defectId": "BGCM2026110304491", "pool": "locatable_only"}])
    assert out.tickets[0].pool == "locatable_only"
    assert out.tickets[0].reasonCode is None
    assert out.tickets[0].clusterId is None
    assert out.tickets[0].priority is None


def test_no_pool_change_keeps_reason():
    """只改 intent 不该动筛因。"""
    batch = validate_defect_batch(_batch("needs_info", "C1c", "vague adjective"))
    out = apply_intent_review(
        batch, [{"defectId": "BGCM2026110304491", "intent": "unclear"}]
    )
    assert out.tickets[0].pool == "needs_info"
    assert out.tickets[0].reasonCode == "C1c"


def test_protected_pools_still_refused():
    batch = validate_defect_batch(_batch("security", "SECURITY", "scanner corpus"))
    with pytest.raises(ValueError):
        apply_intent_review(batch, [{"defectId": "BGCM2026110304491", "pool": "strict"}])
