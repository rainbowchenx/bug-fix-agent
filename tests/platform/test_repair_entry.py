"""正式入口必须走证据门槛；resume 必须跑下一轮。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_contracts.repair import InputRevision
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.cli import main
from bugfix_platform.sdk.analyze import AnalyzeRequest, AnalyzeResult
from bugfix_platform.sdk.fix import FixRequest, FixResult


def _batch(*, pool: str = "strict", observed: str = "黑屏") -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1 if pool == "strict" else 0, "needsInfo": 1 if pool == "needs_info" else 0},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "preview glitch",
                    "pool": pool,
                    "expectQuality": "explicit",
                    "observed": observed,
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


def _real_mechanism_payload(req: AnalyzeRequest, tmp_path: Path, log: Path) -> dict:
    probe = tmp_path / "probe_check.py"
    probe.write_text(
        "from pathlib import Path\n"
        f"log = Path({str(log)!r})\n"
        "src = Path('src/a.ts')\n"
        "log.write_text(str(Path('.').resolve()) + chr(10) + src.read_text(encoding='utf-8'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    second = tmp_path / "probe_second.py"
    second.write_text("print('second-check')\n", encoding="utf-8")
    return {
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
            "notes": "read current src/a.ts",
        },
        "suggestedVerify": {
            "steps": ["compile candidate"],
            "executed": False,
            "commands": [
                {"command": [sys.executable, str(probe)]},
                {"command": [sys.executable, str(second)]},
            ],
        },
    }


def test_checks_run_on_candidate_worktree_not_source(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("BEFORE\n", encoding="utf-8")
    log = tmp_path / "check.log"
    worktrees: list[str] = []

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(ok=True, source="sdk", payload=_real_mechanism_payload(req, tmp_path, log))

    def fake_fix(req: FixRequest) -> FixResult:
        worktrees.append(req.worktree_path)
        Path(req.worktree_path, "src", "a.ts").write_text("AFTER\n", encoding="utf-8")
        return FixResult(
            ok=True,
            source="sdk",
            payload={"outcome": "patch_ready", "patch": {"path": str(tmp_path / "x.diff"), "summary": "after"}},
        )

    (tmp_path / "x.diff").write_text("diff --git a/src/a.ts b/src/a.ts\n+AFTER\n", encoding="utf-8")
    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert (work / "src" / "a.ts").read_text(encoding="utf-8") == "BEFORE\n"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "AFTER" in text
    assert str(work.resolve()) not in text.splitlines()[0]
    assert worktrees
    assert Path(worktrees[0]).resolve() != work.resolve()
    latest = json.loads((tmp_path / "art" / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    checks = attempt.get("checks") or []
    assert len(checks) >= 2
    assert any(item.get("candidateDigest") for item in checks)
    assert report.tickets[0].outcome in ("patch_ready", "plan_only")


def test_revision_unblocks_needs_info_and_enters_fix(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    calls = {"analyze": 0, "fix": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls["analyze"] += 1
        assert req.routed.get("outcome") != "needs_ticket_info"
        assert "camera_disconnected" in (req.ticket.observed or "")
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "camera disconnect not handled",
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
                    "notes": "read current file",
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        calls["fix"] += 1
        return FixResult(
            ok=True,
            source="sdk",
            payload={"outcome": "patch_ready", "patch": {"path": str(tmp_path / "p.diff"), "summary": "guard"}},
        )

    (tmp_path / "p.diff").write_text("diff --git a/src/a.ts b/src/a.ts\n+guard\n", encoding="utf-8")
    run_analyst(
        work_dir=work,
        defect_batch=_batch(pool="needs_info", observed=""),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
        revisions={
            "D1": InputRevision(
                revisionId="D1:f1",
                defectId="D1",
                observed="补充：camera_disconnected",
                expected="预览恢复",
                steps="打开预览后拔相机",
                source="feedback",
            )
        },
    )
    assert calls["analyze"] == 1
    assert calls["fix"] == 1


def test_analyze_session_id_is_persisted_not_invented(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    seen: list = []

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        seen.append(getattr(req, "resume_session_id", None))
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "init race in preview player",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "serialize init", "steps": [], "targetFiles": ["src/a.ts"]},
            },
            session_id="sdk-sess-real",
        )

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        apply_fix=False,
        artifact_dir=tmp_path / "art1",
    )
    attempt = json.loads(
        Path(
            json.loads((tmp_path / "art1" / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))["path"]
        ).read_text(encoding="utf-8")
    )
    assert attempt.get("sessionId") == "sdk-sess-real"
    assert seen[0] in (None, "")

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        apply_fix=False,
        artifact_dir=tmp_path / "art2",
        session_ids={"D1": "sdk-sess-real"},
    )
    assert seen[1] == "sdk-sess-real"
