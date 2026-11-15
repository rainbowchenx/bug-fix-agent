"""T10：写失败不可称成功；第二 writer 返回 busy。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord
from bugfix_platform.agents.analyst.attempt_store import AttemptStoreBusy, save_attempt
from bugfix_platform.agents.analyst.report import render_report


def test_save_attempt_roundtrip_and_busy(tmp_path: Path):
    root = tmp_path / "art"
    attempt = AttemptRecord.model_validate(
        {
            "schemaVersion": REPAIR_SCHEMA_VERSION,
            "attemptId": "a1",
            "defectId": "D1",
            "execution": "completed",
            "resolution": "analysis_only",
            "patchDelivery": "none",
        }
    )
    path = save_attempt(root, attempt)
    assert path.is_file()
    (root / ".write.lock").write_text("held", encoding="utf-8")
    with pytest.raises(AttemptStoreBusy):
        save_attempt(root, attempt)
    text = render_report(
        {
            "batchId": "b1",
            "tickets": [{"defectId": "D1", "resolution": "analysis_only"}],
        }
    )
    assert "D1" in text
    assert "analysis_only" in text


def test_run_analyst_persists_all_tickets_including_excluded(tmp_path: Path):
    from bugfix_contracts import CodeKnowledge, DefectBatch
    from bugfix_platform.agents.analyst import run_analyst
    from bugfix_platform.sdk.analyze import AnalyzeRequest, AnalyzeResult

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 2, "strict": 1, "excluded": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "preview glitch",
                    "pool": "strict",
                    "expectQuality": "explicit",
                },
                {
                    "defectId": "D2",
                    "title": "cancelled",
                    "pool": "excluded",
                    "expectQuality": "absent",
                    "reasonCode": "R1",
                },
            ],
        }
    )
    knowledge = CodeKnowledge.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(work),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "unknown",
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "why": "token",
                            "source": "heuristic",
                        }
                    ],
                    "confidence": "low",
                }
            ],
        }
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "init race",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "serialize init",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
            },
        )

    art = tmp_path / "art"
    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=fake_analyze,
        artifact_dir=art,
    )
    assert {t.defectId for t in report.tickets} == {"D1", "D2"}
    excluded = next(t for t in report.tickets if t.defectId == "D2")
    assert excluded.outcome == "other_blocked"
    assert (art / "defects" / "D1" / "latest.json").is_file()
    assert (art / "defects" / "D2" / "latest.json").is_file()
    md = art / "analysis-report.md"
    assert md.is_file()
    text = md.read_text(encoding="utf-8")
    assert "D1" in text and "D2" in text
    assert "init race" in text
    latest = json.loads((art / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    assert attempt.get("evidence") or attempt.get("revisionId")
    assert attempt.get("editDecision") is not None or attempt.get("resolution") == "analysis_only"
