from pathlib import Path

from bugfix_agent.contracts.defect_batch import RawDefectsFile
from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.scripts.csv_to_raw_defects import convert

ROOT = Path(__file__).resolve().parents[1]
CSV_87 = ROOT / "缺陷拉取" / "脱敏" / "PJ14PD20260423284-assignee-87.csv"
RAW_87 = ROOT / "缺陷拉取" / "脱敏" / "PJ14PD20260423284-assignee-87.raw-defects.json"


def test_csv_convert_assignee_87():
    payload = convert(CSV_87, "ax-hybrid", limit=None)
    assert payload["productLine"] == "ax-hybrid"
    assert len(payload["defects"]) == 87
    d0 = payload["defects"][0]
    assert d0["defectId"].startswith("BG")
    assert d0["title"]
    assert "description" in d0
    assert d0.get("status") == "Open"
    assert d0.get("testModule")
    # people / flowInstId must not leak into core fields
    assert "devName" not in d0
    assert "flowInstId" not in d0
    parsed = RawDefectsFile.model_validate(payload)
    assert len(parsed.defects) == 87


def test_committed_raw_defects_feeds_agent1():
    assert RAW_87.is_file(), "run csv_to_raw_defects.py to refresh committed entry data"
    batch = run_defect_batch_prepare(
        product_line="ax-hybrid",
        posture="beta",
        source=RAW_87,
    )
    assert batch.funnel["total"] == 87
    assert batch.funnel["excluded"] == 0
    assert batch.funnel["strict"] >= 1
    assert all((t.status or "") in {"Open", "New"} for t in batch.tickets if t.pool == "strict")
