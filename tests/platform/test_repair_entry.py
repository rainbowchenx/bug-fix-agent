"""正式入口必须走证据门槛；resume 必须跑下一轮。"""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.cli import main
from bugfix_platform.sdk.analyze import AnalyzeRequest, AnalyzeResult
from bugfix_platform.sdk.fix import FixRequest, FixResult


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
                    "title": "preview glitch",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "observed": "黑屏",
                    "expected": "出画",
                    "steps": "打开预览",
                }
            ],
        }
    )


def _knowledge(work: Path) -> CodeKnowledge:
    return CodeKnowledge.model_validate(
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


def test_placeholder_root_cause_does_not_enter_fix(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    called = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "TODO 分析中待补充",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "maybe edit",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(ok=True, payload={"outcome": "patch_ready", "patch": {"path": "x"}})

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert called["n"] == 0
    assert report.tickets[0].outcome != "patch_ready"


def test_resume_cli_runs_second_analyst(tmp_path: Path, monkeypatch):
    root = tmp_path / "out"
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    batch = _batch()
    knowledge = _knowledge(work)
    (root / "defects" / "D1" / "feedback").mkdir(parents=True)
    report = {
        "schemaVersion": "0.1.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "openMr": False,
        "applyFix": True,
        "tickets": [
            {
                "defectId": "D1",
                "outcome": "needs_ticket_info",
                "ticket": {"title": "preview glitch", "pool": "strict"},
                "rootCause": {"summary": "need logs", "ruledOut": [], "openQuestions": []},
                "blockers": {"kind": "needs_ticket_info", "detail": "logs"},
                "suggestedVerify": {"steps": [], "executed": False},
                "confidence": "low",
                "verifyStatus": "skipped",
            }
        ],
        "summary": {"total": 1, "byOutcome": {"needs_ticket_info": 1}},
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "defect-batch.json").write_text(batch.model_dump_json(), encoding="utf-8")
    (root / "code-knowledge.json").write_text(knowledge.model_dump_json(), encoding="utf-8")
    (root / "analysis-report.json").write_text(json.dumps(report), encoding="utf-8")
    (root / "defects" / "D1" / "feedback" / "f1.json").write_text(
        json.dumps(
            {
                "feedback": {
                    "feedbackId": "f1",
                    "defectId": "D1",
                    "text": "补充：camera_disconnected",
                    "application": "not_applied",
                    "acceptance": "rejected",
                },
                "revision": {
                    "revisionId": "D1:f1",
                    "defectId": "D1",
                    "observed": "补充：camera_disconnected",
                    "source": "feedback",
                },
            }
        ),
        encoding="utf-8",
    )
    seen: dict = {}

    def fake_run_analyst(**kwargs):
        from bugfix_contracts.analysis_report import AnalysisReport

        seen.update(kwargs)
        return AnalysisReport.model_validate(
            {
                "schemaVersion": "0.1.0",
                "productLine": "hc",
                "workDir": str(work),
                "generatedAt": "2026-01-01T00:00:00Z",
                "applyFix": True,
                "tickets": [
                    {
                        "defectId": "D1",
                        "outcome": "plan_only",
                        "proposedFix": {
                            "summary": "handle camera_disconnected",
                            "steps": [],
                            "targetFiles": ["src/a.ts"],
                        },
                        "rootCause": {
                            "summary": "disconnect path",
                            "ruledOut": [],
                            "openQuestions": [],
                        },
                        "suggestedVerify": {"steps": [], "executed": False},
                        "confidence": "medium",
                        "verifyStatus": "skipped",
                    }
                ],
                "summary": {"total": 1, "byOutcome": {"plan_only": 1}},
            }
        )

    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.run_analyst", fake_run_analyst
    )
    rc = main(["resume", "--root", str(root), "--defect-id", "D1", "--apply-fix"])
    assert rc == 0
    assert seen.get("apply_fix") is True
    revisions = seen.get("revisions") or {}
    rev = revisions.get("D1")
    assert rev is not None
    observed = rev.observed if hasattr(rev, "observed") else rev.get("observed")
    assert observed and "camera_disconnected" in observed


def test_resume_cli_executes_analyze_and_fix(tmp_path: Path, monkeypatch):
    """CLI resume --apply-fix 必须真正进入分析/编辑，而不是只写 session-decision。"""
    root = tmp_path / "out"
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    patch_path = tmp_path / "D1.patch"
    patch_path.write_text("diff --git a/src/a.ts b/src/a.ts\n+guard();\n", encoding="utf-8")
    batch = _batch()
    knowledge = _knowledge(work)
    root.mkdir(parents=True)
    (root / "defects" / "D1" / "feedback").mkdir(parents=True)
    (root / "defect-batch.json").write_text(batch.model_dump_json(), encoding="utf-8")
    (root / "code-knowledge.json").write_text(knowledge.model_dump_json(), encoding="utf-8")
    (root / "analysis-report.json").write_text(
        json.dumps(
            {
                "schemaVersion": "0.1.0",
                "productLine": "hc",
                "workDir": str(work),
                "generatedAt": "2026-01-01T00:00:00Z",
                "applyFix": True,
                "tickets": [
                    {
                        "defectId": "D1",
                        "outcome": "needs_ticket_info",
                        "blockers": {"kind": "needs_ticket_info", "detail": "logs"},
                        "rootCause": {"summary": "need logs", "ruledOut": [], "openQuestions": []},
                        "suggestedVerify": {"steps": [], "executed": False},
                        "confidence": "low",
                        "verifyStatus": "skipped",
                    }
                ],
                "summary": {"total": 1, "byOutcome": {"needs_ticket_info": 1}},
            }
        ),
        encoding="utf-8",
    )
    (root / "defects" / "D1" / "feedback" / "f1.json").write_text(
        json.dumps(
            {
                "feedback": {
                    "feedbackId": "f1",
                    "defectId": "D1",
                    "text": "补充：camera_disconnected",
                    "application": "not_applied",
                    "acceptance": "rejected",
                },
                "revision": {
                    "revisionId": "D1:f1",
                    "defectId": "D1",
                    "observed": "补充：camera_disconnected",
                    "source": "feedback",
                },
            }
        ),
        encoding="utf-8",
    )
    calls = {"analyze": 0, "fix": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls["analyze"] += 1
        assert "camera_disconnected" in (req.ticket.observed or "")
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "disconnect path in preview player",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "handle camera_disconnected",
                    "steps": ["guard"],
                    "targetFiles": ["src/a.ts"],
                },
                "localization": {
                    "candidates": [
                        {"repoPath": ".", "path": "src/a.ts", "why": "player", "source": "grep"}
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        calls["fix"] += 1
        return FixResult(
            ok=True,
            source="sdk",
            payload={
                "outcome": "patch_ready",
                "patch": {"path": str(patch_path), "summary": "guard disconnect"},
            },
        )

    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.create_analyze_runner",
        lambda *_a, **_k: fake_analyze,
    )
    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.create_fix_runner",
        lambda *_a, **_k: fake_fix,
    )
    rc = main(["resume", "--root", str(root), "--defect-id", "D1", "--apply-fix"])
    assert rc == 0
    assert calls["analyze"] == 1
    assert calls["fix"] == 1
    updated = json.loads((root / "analysis-report.json").read_text(encoding="utf-8"))
    assert updated["tickets"][0]["outcome"] == "patch_ready"
    latest = json.loads((root / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    assert attempt.get("patchSet") or attempt.get("patchDelivery") == "candidate"
    assert attempt.get("revisionId") == "D1:f1"


def test_run_analyst_uses_revision_observed(tmp_path: Path):
    from bugfix_contracts.repair import InputRevision

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    seen: dict = {}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        seen["observed"] = req.ticket.observed
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "disconnect path",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "handle camera_disconnected",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
            },
        )

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        apply_fix=False,
        artifact_dir=tmp_path / "art",
        revisions={
            "D1": InputRevision(
                revisionId="D1:f1",
                defectId="D1",
                observed="补充：camera_disconnected",
                source="feedback",
            )
        },
    )
    assert "camera_disconnected" in str(seen.get("observed") or "")
