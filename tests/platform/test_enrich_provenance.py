"""产物必须能自证：Agent-2/3 到底调用没调用 LLM。

修之前三种情形（heuristic / 缺凭据的 sdk / SDK 未安装的 sdk）产物**完全同形**，
`architecture.summary` 一律写 `cartography enrich skipped (heuristic mode)`，
把「本来要走 LLM 但失败」说成「模式就是 heuristic」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bugfix_contracts.defect_batch import DefectBatch
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.sdk.analyze import AnalyzeRequest, AnalyzeResult, heuristic_analyze
from bugfix_platform.sdk.cartography import (
    CartographyRequest,
    CartographyResult,
    heuristic_cartography,
)

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "repos"

_TICKET = {
    "defectId": "D1",
    "title": "盒子校准失败",
    "pool": "strict",
    "testModule": "boxCalibration",
    "titleTag": "boxCalibration",
    "intent": "logic",
    "expectQuality": "explicit",
    "fieldType": "缺陷",
    "description": "【测试步骤】点击校准\n【预期结果】校准成功\n【实际结果】提示失败",
}


def _batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [_TICKET],
        }
    )


def _stub(source: str, detail: str | None):
    """Agent-2 runner 桩：保留 heuristic 产物，只改 source/detail。"""

    def runner(req: CartographyRequest) -> CartographyResult:
        result = heuristic_cartography(req)
        result.source = source  # type: ignore[assignment]
        result.detail = detail
        return result

    return runner


def _analyze_stub(source: str, detail: str | None):
    """Agent-3 runner 桩，同上。"""

    def runner(req: AnalyzeRequest) -> AnalyzeResult:
        result = heuristic_analyze(req)
        result.source = source  # type: ignore[assignment]
        result.detail = detail
        return result

    return runner


def test_agent2_records_heuristic_source():
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    hints = [h for h in knowledge.secondaryHints if h.startswith("enrich=")]
    assert hints == ["enrich=heuristic"], knowledge.secondaryHints


def test_agent2_fallback_reason_survives_into_artifact():
    reason = "claude-agent-sdk not installed (No module named 'claude_agent_sdk')"
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_profile="electron_node",
        cartography_fn=_stub("sdk_fallback", reason),
    )
    hints = [h for h in knowledge.secondaryHints if h.startswith("enrich=")]
    assert len(hints) == 1
    assert hints[0].startswith("enrich=sdk_fallback; ")
    assert "claude-agent-sdk not installed" in hints[0]


def test_agent2_hint_is_not_duplicated_across_runs():
    runner = _stub("sdk", None)
    first = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_profile="electron_node",
        cartography_fn=runner,
    )
    # 再跑一次，把上次的产物当作 baseline 传回去
    again = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_profile="electron_node",
        cartography_fn=runner,
    )
    for knowledge in (first, again):
        hints = [h for h in knowledge.secondaryHints if h.startswith("enrich=")]
        assert hints == ["enrich=sdk"], knowledge.secondaryHints


def test_agent3_notes_carry_analyze_source():
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    report = run_analyst(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        code_knowledge=knowledge,
        analyze_mode="heuristic",
    )
    notes = report.tickets[0].localization.notes or ""
    assert "analyze=heuristic" in notes, notes


def test_agent3_fallback_reason_survives_into_artifact():
    reason = "no Anthropic credentials in env"
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    report = run_analyst(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch(),
        code_knowledge=knowledge,
        analyze_fn=_analyze_stub("sdk_fallback", reason),
    )
    notes = report.tickets[0].localization.notes or ""
    assert "analyze=sdk_fallback" in notes, notes
    assert reason in notes, notes
