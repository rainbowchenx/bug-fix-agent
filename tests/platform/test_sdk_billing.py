"""SDK 会话必须自带账单：`enrich=sdk; turns=17; reason=completed; cost=$0.42`。

`ResultMessage` 里本来就有 `num_turns` / `total_cost_usd` / `terminal_reason`，
之前一个都没接——于是「放开 max_turns」等于把钱交给一个不报账的进程。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bugfix_contracts.defect_batch import DefectBatch
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.sdk.cartography import _billing

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "repos"


def _batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "盒子校准失败",
                    "pool": "strict",
                    "testModule": "boxCalibration",
                    "titleTag": "boxCalibration",
                    "intent": "logic",
                    "expectQuality": "explicit",
                    "fieldType": "缺陷",
                }
            ],
        }
    )


def _result(**kw: Any):
    from claude_agent_sdk.types import ResultMessage

    payload = {
        "subtype": "success",
        "duration_ms": 1000,
        "duration_api_ms": 900,
        "is_error": False,
        "num_turns": 3,
        "session_id": "s-1",
        "result": "",
        "structured_output": {"architecture": {"summary": "enriched by stub"}},
        "total_cost_usd": 0.4237,
        "terminal_reason": "completed",
    }
    payload.update(kw)
    return ResultMessage(**payload)


def _install_fake_query(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> None:
    """替换 SDK 的 query；import 在函数内部，所以改模块属性即可生效。"""
    import claude_agent_sdk

    async def fake_query(*, prompt: str, options: Any):
        for message in messages:
            yield message

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_billing_formats_turns_reason_cost():
    assert _billing(17, 0.4237, "completed") == "turns=17; reason=completed; cost=$0.42"
    assert _billing(1, 0.0031, "max_turns") == "turns=1; reason=max_turns; cost=$0.0031"
    assert _billing(None, None, None) == ""


def test_success_records_billing_in_artifact(monkeypatch):
    _install_fake_query(monkeypatch, [_result()])
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_mode="sdk",
        cartography_profile="electron_node",
    )
    hints = [h for h in knowledge.secondaryHints if h.startswith("enrich=")]
    assert len(hints) == 1, knowledge.secondaryHints
    assert hints[0].startswith("enrich=sdk; turns=3; reason=completed; cost=$0.42"), hints[0]


def test_max_turns_fallback_records_billing_and_reason(monkeypatch):
    _install_fake_query(
        monkeypatch,
        [
            _result(
                is_error=True,
                subtype="error_max_turns",
                errors=["Reached maximum number of turns (18)"],
                result=None,
                structured_output=None,
                num_turns=18,
                total_cost_usd=1.5,
                terminal_reason="max_turns",
            )
        ],
    )
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_mode="sdk",
        cartography_profile="electron_node",
    )
    hint = next(h for h in knowledge.secondaryHints if h.startswith("enrich="))
    assert hint.startswith("enrich=sdk_fallback; "), hint
    assert "maximum number of turns" in hint
    assert "turns=18" in hint
    assert "reason=max_turns" in hint
    assert "cost=$1.50" in hint
