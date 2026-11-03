from pathlib import Path

from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.ingest import FIELD_ALIASES, load_platform_csv, load_preloaded, row_to_raw_dict

ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "缺陷拉取" / "脱敏"
CSV_87 = CSV_DIR / "PJ14PD20260423284-assignee-87.csv"
CSV_416 = CSV_DIR / "PJ14PD20260509167-reporter-resolver-416.csv"


def test_field_map_platform_row():
    mapped = row_to_raw_dict(
        {
            "defectId": "BGCM1",
            "defectTitle": "[模块] 标题",
            "describle": "预期结果：应显示\n实际结果：未显示",
            "defectStatus": "Open",
            "flowStatusName": "解决缺陷",
            "severityName": "低",
            "testModule": "报警推送",
            "createDate": "2026-11-03 14:59:15",
            "softName": "AX",
            "flowInstId": "********",
        }
    )
    assert mapped is not None
    assert mapped["title"] == "[模块] 标题"
    assert mapped["description"].startswith("预期结果")
    assert mapped["status"] == "Open"
    assert mapped["flowStatus"] == "解决缺陷"
    assert mapped["severity"] == "低"
    assert mapped["createdAt"].startswith("2026")
    assert mapped["metadata"]["softName"] == "AX"
    assert "flowInstId" not in mapped["metadata"]  # redacted


def test_describle_alias_listed():
    assert "describle" in FIELD_ALIASES["description"]
    assert "defectTitle" in FIELD_ALIASES["title"]


def test_load_csv_87():
    defects = load_platform_csv(CSV_87)
    assert len(defects) == 87
    assert defects[0].defectId.startswith("BGCM")
    assert defects[0].title
    assert defects[0].status == "Open"


def test_load_preloaded_accepts_csv_path():
    defects = load_preloaded(CSV_87)
    assert len(defects) == 87


def test_agent1_prepare_from_platform_csv_beta():
    batch = run_defect_batch_prepare(
        product_line="sample",
        posture="beta",
        source=CSV_87,
    )
    assert batch.funnel["total"] == 87
    # beta keeps Open/New in functional pools; Closed/etc excluded or security
    functional = [t for t in batch.tickets if t.pool not in ("excluded", "security")]
    assert functional
    assert all((t.status or "") in {"Open", "New"} for t in functional)


def test_agent1_prepare_from_larger_csv_alpha():
    batch = run_defect_batch_prepare(
        product_line="sample",
        posture="alpha",
        source=CSV_416,
    )
    assert batch.funnel["total"] == 416
    assert batch.funnel["excluded"] + batch.funnel["locatable_only"] + batch.funnel["strict"] + batch.funnel[
        "needs_info"
    ] + batch.funnel["hard_reject"] + batch.funnel["security"] == 416
