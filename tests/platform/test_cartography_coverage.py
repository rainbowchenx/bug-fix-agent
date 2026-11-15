"""T08：超过 16 票不得静默假完成。"""

from bugfix_contracts.code_knowledge import DefectCodeMatch
from bugfix_platform.sdk.cartography import annotate_investigation_coverage


def test_overflow_tickets_are_not_investigated():
    matches = [
        DefectCodeMatch(defectId=f"D{i}", candidates=[], confidence="low")
        for i in range(20)
    ]
    prompt_ids = [f"D{i}" for i in range(16)]
    out = annotate_investigation_coverage(matches, prompt_ids=prompt_ids, investigated_ids=["D0", "D1"])
    by_id = {m.defectId: m for m in out}
    assert by_id["D0"].investigationStatus in ("partial", "complete")
    assert by_id["D16"].investigationStatus == "not_investigated"
    assert by_id["D19"].investigationStatus == "not_investigated"


def test_zero_candidates_remain_legal():
    matches = [DefectCodeMatch(defectId="D1", candidates=[], confidence="low")]
    out = annotate_investigation_coverage(matches, prompt_ids=["D1"], investigated_ids=["D1"])
    assert out[0].candidates == []
    assert out[0].investigationStatus in ("partial", "complete")
