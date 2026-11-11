"""Agent-3 报告打分脚本：G0 / loc@k / outcome。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))

from eval_agent3 import loc_hit, score_report, score_ticket  # noqa: E402


def _ticket(**kw):
    base = {
        "defectId": "D1",
        "ticket": {"title": "osd overlay", "pool": "strict"},
        "localization": {
            "candidates": [
                {"repoPath": ".", "path": "src/Config/view/snap/foo.vue", "why": "osd"}
            ],
            "notes": "analyze=sdk; turns=8; reason=completed",
        },
        "rootCause": {"summary": "小图坐标换算越界", "ruledOut": [], "openQuestions": []},
        "outcome": "plan_only",
        "proposedFix": {"summary": "钳制 overlay 坐标", "steps": [], "targetFiles": []},
        "suggestedVerify": {"steps": [], "executed": False},
        "confidence": "medium",
        "verifyStatus": "skipped",
    }
    base.update(kw)
    return base


def _report(tickets: list[dict]) -> dict:
    return {
        "schemaVersion": "0.1.0",
        "productLine": "hc",
        "workDir": "/tmp/repo",
        "generatedAt": "2026-01-01T00:00:00Z",
        "openMr": False,
        "applyFix": False,
        "tickets": tickets,
        "summary": {"total": len(tickets), "byOutcome": {}},
    }


def test_loc_hit_prefix():
    cands = [{"path": "src/Config/view/snap/osd.vue", "repoPath": "."}]
    assert loc_hit(cands, "src/Config/view/snap/", 3) is True
    assert loc_hit(cands, "src/Preview/", 3) is False


def test_g0_fails_on_patch_ready_and_entry_noise():
    case = {
        "defectId": "D1",
        "pool": "strict",
        "expectPathPrefix": "src/Config/view/snap/",
        "expectOutcomes": ["plan_only"],
    }
    ready = score_ticket(case, _ticket(outcome="patch_ready"))
    assert ready["g0Pass"] is False
    assert "patch_ready_on_report_path" in ready["g0"]

    noisy = score_ticket(
        case,
        _ticket(
            localization={
                "candidates": [
                    {"repoPath": ".", "path": "src/Router/mobile.js", "why": "dual-entry"}
                ],
                "notes": "analyze=sdk",
            },
            confidence="medium",
        ),
    )
    assert noisy["g0Pass"] is False
    assert "entry_noise_confident" in noisy["g0"]
    assert noisy["locAt3"] is False


def test_needs_info_must_not_run_sdk():
    case = {
        "defectId": "N1",
        "pool": "needs_info",
        "expectOutcomes": ["needs_ticket_info"],
    }
    bad = score_ticket(
        case,
        _ticket(
            defectId="N1",
            outcome="needs_ticket_info",
            localization={"candidates": [], "notes": "analyze=sdk"},
            proposedFix=None,
            blockers={"kind": "needs_ticket_info", "detail": "missing steps"},
        ),
    )
    assert bad["g0Pass"] is False
    assert "needs_info_ran_sdk" in bad["g0"]


def test_score_report_usable_when_loc_and_outcome_hit(tmp_path: Path):
    report = _report([_ticket()])
    cases = [
        {
            "id": "osd",
            "defectId": "D1",
            "pool": "strict",
            "expectPathPrefix": "src/Config/view/snap/",
            "expectOutcomes": ["plan_only"],
            "rootCauseMustInclude": ["坐标"],
        }
    ]
    scored = score_report(report, cases)
    assert scored["summary"]["g0Pass"] is True
    assert scored["summary"]["locAt3"] == "1/1"
    assert scored["summary"]["outcome"] == "1/1"
    assert scored["summary"]["verdict"] == "usable_pending_g3"
    assert scored["rows"][0]["rootCauseWeakOk"] is True

    # 落盘形状稳定，方便实场对照。
    out = tmp_path / "score.json"
    out.write_text(json.dumps(scored), encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["g0Pass"] is True
