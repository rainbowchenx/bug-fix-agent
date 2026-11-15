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
    (work / "src" / "a.ts").write_text("function preview() { return; }\n", encoding="utf-8")
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
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "why": "player",
                            "snippet": "function preview() { return; }",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        calls["fix"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function preview() { guard(); return; }\n", encoding="utf-8"
        )
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
                {
                    "repoPath": ".",
                    "path": "src/a.ts",
                    "why": "player",
                    "snippet": "function preview() { BEFORE }",
                    "source": "grep",
                }
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
    (work / "src" / "a.ts").write_text("function preview() { BEFORE }\n", encoding="utf-8")
    log = tmp_path / "check.log"
    worktrees: list[str] = []

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(ok=True, source="sdk", payload=_real_mechanism_payload(req, tmp_path, log))

    def fake_fix(req: FixRequest) -> FixResult:
        worktrees.append(req.worktree_path)
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function preview() { AFTER }\n", encoding="utf-8"
        )
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
    assert (work / "src" / "a.ts").read_text(encoding="utf-8") == "function preview() { BEFORE }\n"
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
    (work / "src" / "a.ts").write_text("function preview() { disconnect(); }\n", encoding="utf-8")
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
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "why": "player",
                            "snippet": "function preview() { disconnect(); }",
                            "source": "grep",
                        }
                    ],
                    "notes": "read current file",
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        calls["fix"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function preview() { handle camera_disconnected; }\n", encoding="utf-8"
        )
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


def test_file_exists_without_mechanism_token_does_not_enter_fix(tmp_path: Path):
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
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "rethrow in handleFail",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
                "localization": {
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "symbol": "handleFail",
                            "why": "name",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
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


def test_repo_path_reads_nested_repo_file(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    nested = work / "apps" / "player" / "src"
    nested.mkdir(parents=True)
    (nested / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    called = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "rethrow in handleFail",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
                "localization": {
                    "candidates": [
                        {
                            "repoPath": "apps/player",
                            "path": "src/a.ts",
                            "symbol": "handleFail",
                            "why": "player",
                            "snippet": "function handleFail() { return; }",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(
            ok=True,
            source="sdk",
            payload={"outcome": "patch_ready", "patch": {"path": str(tmp_path / "p.diff"), "summary": "x"}},
        )

    (tmp_path / "p.diff").write_text("diff --git a/src/a.ts b/src/a.ts\n@@ handleFail\n+x\n", encoding="utf-8")
    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert called["n"] == 1


def test_report_uses_namespaced_patchset_not_fixer_slug(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    slug = tmp_path / "art" / "D1.patch"
    slug.parent.mkdir()
    slug.write_text("OLD-SDK-PATCH\n", encoding="utf-8")

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "rethrow in handleFail",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
                "localization": {
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "symbol": "handleFail",
                            "why": "player",
                            "snippet": "function handleFail() { return; }",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(
            ok=True,
            source="sdk",
            payload={"outcome": "patch_ready", "patch": {"path": str(slug), "summary": "sdk slug"}},
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    path = report.tickets[0].patch.path if report.tickets[0].patch else ""
    assert path
    assert Path(path).name != "D1.patch"
    assert "OLD-SDK-PATCH" not in Path(path).read_text(encoding="utf-8", errors="replace")


def test_source_change_during_analyze_blocks_edit(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    called = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        Path(req.work_dir, "src", "a.ts").write_text("MUTATED_DURING_ANALYZE\n", encoding="utf-8")
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "rethrow",
                    "steps": [],
                    "targetFiles": ["src/a.ts"],
                },
                "localization": {
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "symbol": "handleFail",
                            "why": "x",
                            "snippet": "function handleFail() { return; }",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(ok=True, payload={"outcome": "patch_ready", "patch": {"path": "x"}})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert called["n"] == 0


def test_one_ticket_exception_does_not_stop_batch(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 2, "strict": 2},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "one",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "observed": "a",
                    "expected": "b",
                    "steps": "s",
                },
                {
                    "defectId": "D2",
                    "title": "two",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "observed": "a",
                    "expected": "b",
                    "steps": "s",
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
                {"defectId": "D1", "candidates": [], "confidence": "low"},
                {
                    "defectId": "D2",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "why": "token",
                            "source": "heuristic",
                        }
                    ],
                    "confidence": "low",
                },
            ],
        }
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        if req.ticket.defectId == "D1":
            raise RuntimeError("boom analyze")
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=fake_analyze,
        apply_fix=False,
        artifact_dir=tmp_path / "art",
    )
    ids = {t.defectId: t.outcome for t in report.tickets}
    assert ids["D1"] == "other_blocked"
    assert ids["D2"] != "other_blocked" or report.tickets[1].rootCause.summary


def test_resume_keeps_other_tickets_and_round_report(tmp_path: Path, monkeypatch):
    root = tmp_path / "out"
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    root.mkdir()
    (root / "defects" / "D1" / "feedback").mkdir(parents=True)
    batch = DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 2, "strict": 2},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "one",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "observed": "a",
                    "expected": "b",
                    "steps": "s",
                },
                {
                    "defectId": "D2",
                    "title": "two",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "observed": "a",
                    "expected": "b",
                    "steps": "s",
                },
            ],
        }
    )
    knowledge = _knowledge(work)
    previous = {
        "schemaVersion": "0.1.0",
        "productLine": "hc",
        "workDir": str(work),
        "generatedAt": "2026-01-01T00:00:00Z",
        "applyFix": False,
        "tickets": [
            {
                "defectId": "D1",
                "outcome": "needs_ticket_info",
                "blockers": {"kind": "needs_ticket_info", "detail": "logs"},
                "rootCause": {"summary": "need logs", "ruledOut": [], "openQuestions": []},
                "suggestedVerify": {"steps": [], "executed": False},
                "confidence": "low",
                "verifyStatus": "skipped",
            },
            {
                "defectId": "D2",
                "outcome": "plan_only",
                "proposedFix": {"summary": "leave D2", "steps": [], "targetFiles": []},
                "rootCause": {"summary": "other ticket", "ruledOut": [], "openQuestions": []},
                "suggestedVerify": {"steps": [], "executed": False},
                "confidence": "low",
                "verifyStatus": "skipped",
            },
        ],
        "summary": {"total": 2, "byOutcome": {"needs_ticket_info": 1, "plan_only": 1}},
    }
    (root / "defect-batch.json").write_text(batch.model_dump_json(), encoding="utf-8")
    (root / "code-knowledge.json").write_text(knowledge.model_dump_json(), encoding="utf-8")
    (root / "analysis-report.json").write_text(json.dumps(previous), encoding="utf-8")
    (root / "defects" / "D1" / "feedback" / "f1.json").write_text(
        json.dumps(
            {
                "feedback": {
                    "feedbackId": "f1",
                    "defectId": "D1",
                    "application": "not_applied",
                    "acceptance": "rejected",
                    "text": "补充：camera_disconnected",
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

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
            },
        )

    monkeypatch.setattr(
        "bugfix_platform.agents.analyst.run.create_analyze_runner",
        lambda *_a, **_k: fake_analyze,
    )
    rc = main(["resume", "--root", str(root), "--defect-id", "D1", "--apply-fix"])
    assert rc == 0
    updated = json.loads((root / "analysis-report.json").read_text(encoding="utf-8"))
    ids = {t["defectId"] for t in updated["tickets"]}
    assert ids == {"D1", "D2"}
    rounds = list((root / "rounds").glob("*.json")) if (root / "rounds").is_dir() else []
    assert rounds, "expected a per-round report file"


def test_resume_not_applied_patch_is_marked_replaced(tmp_path: Path):
    from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, PatchFile, PatchSet
    from bugfix_platform.agents.analyst.attempt_store import save_attempt

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("function handleFail() { return; }\n", encoding="utf-8")
    art = tmp_path / "art"
    old = PatchSet(
        patchSetId="oldpatch",
        delivery="candidate",
        patches=[
            PatchFile(
                path="src/a.ts",
                kind="modify",
                digest="deadbeefdeadbeef",
                archivePath=str(tmp_path / "old.diff"),
            )
        ],
    )
    save_attempt(
        art,
        AttemptRecord.model_validate(
            {
                "schemaVersion": REPAIR_SCHEMA_VERSION,
                "attemptId": "a0",
                "defectId": "D1",
                "execution": "completed",
                "resolution": "patch_produced",
                "patchDelivery": "candidate",
                "patchSet": old.model_dump(),
            }
        ),
    )
    feedback_dir = art / "defects" / "D1" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    (feedback_dir / "f1.json").write_text(
        json.dumps(
            {
                "feedback": {
                    "feedbackId": "f1",
                    "defectId": "D1",
                    "application": "not_applied",
                    "acceptance": "rejected",
                    "text": "未应用旧补丁，请换方案",
                },
                "revision": {
                    "revisionId": "D1:f1",
                    "defectId": "D1",
                    "observed": "未应用旧补丁，请换方案",
                    "source": "feedback",
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": {
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "symbol": "handleFail",
                            "why": "x",
                            "snippet": "function handleFail() { return; }",
                            "source": "grep",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(
            ok=True,
            source="sdk",
            payload={"outcome": "patch_ready", "patch": {"path": str(tmp_path / "n.diff"), "summary": "x"}},
        )

    (tmp_path / "n.diff").write_text("x\n", encoding="utf-8")
    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=art,
        revisions={
            "D1": InputRevision(
                revisionId="D1:f1",
                defectId="D1",
                observed="未应用旧补丁，请换方案",
                source="feedback",
            )
        },
    )
    latest = json.loads((art / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    patch = attempt.get("patchSet") or {}
    assert patch.get("replaces") == "oldpatch"


_SNIPPET = "function handleFail() { return; }"


def _loc(*extra: dict) -> dict:
    cand = {
        "repoPath": ".",
        "path": "src/a.ts",
        "symbol": "handleFail",
        "why": "handleFail swallows the error",
        "snippet": _SNIPPET,
        "source": "grep",
    }
    cand.update(extra[0] if extra else {})
    return {
        "candidates": [cand],
        "notes": "",
    }


def test_sdk_json_without_snippet_survives_parse_as_locator(tmp_path: Path):
    from bugfix_platform.sdk.analyze import _merge_with_routed, parse_analyze_payload

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    called = {"n": 0}
    raw = (
        "```json\n"
        '{"outcome":"plan_only","rootCause":{"summary":"handleFail swallows camera errors",'
        '"ruledOut":[],"openQuestions":[]},"proposedFix":{"summary":"rethrow","steps":[],'
        '"targetFiles":["src/a.ts"]},"localization":{"candidates":[{"repoPath":".","path":"src/a.ts",'
        '"symbol":"handleFail","why":"empty catch","source":"sdk"}],"notes":""},"confidence":"medium"}\n'
        "```"
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        parsed = parse_analyze_payload(raw)
        payload = _merge_with_routed(
            req.routed,
            parsed or {},
            work_dir=req.work_dir,
            apply_fix=True,
        )
        return AnalyzeResult(ok=True, source="sdk", payload=payload)

    def fake_fix(req: FixRequest) -> FixResult:
        called["n"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

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
    loc = report.tickets[0].localization.candidates
    assert loc and (loc[0].snippet or "") and _SNIPPET.split("{")[0].strip() in (loc[0].snippet or "")
    assert report.tickets[0].outcome != "patch_ready"


def test_cited_snippet_missing_from_file_does_not_enter_fix(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    called = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": {
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/a.ts",
                            "symbol": "preview",
                            "why": "wrong fragment",
                            "snippet": "function handleFail() { return; }",
                            "source": "sdk",
                        }
                    ],
                    "notes": "",
                },
            },
        )

    def fake_fix(_req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(ok=True, payload={"outcome": "patch_ready"})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert called["n"] == 0


def test_multifile_patch_bundle_applies_complete_fix(tmp_path: Path):
    import subprocess

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {
                    "summary": "rethrow via helper",
                    "steps": [],
                    "targetFiles": ["src/a.ts", "src/helper.ts"],
                },
                "localization": _loc(),
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\nimport { report } from './helper';\n",
            encoding="utf-8",
        )
        Path(req.worktree_path, "src", "helper.ts").write_text(
            "export function report(e) { return e; }\n",
            encoding="utf-8",
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready", "patch": {"path": "x"}})

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    ticket = report.tickets[0]
    assert ticket.outcome == "patch_ready"
    bundle = Path(str(ticket.patch.path if ticket.patch else ""))
    assert bundle.is_file()
    text = bundle.read_text(encoding="utf-8", errors="replace")
    assert "src/a.ts" in text.replace("\\", "/")
    assert "src/helper.ts" in text.replace("\\", "/")
    check = tmp_path / "apply"
    check.mkdir()
    (check / "src").mkdir()
    (check / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["git", "apply", "--check", str(bundle)],
        cwd=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    subprocess.run(["git", "apply", str(bundle)], cwd=check, check=True, capture_output=True)
    assert "helper" in (check / "src" / "a.ts").read_text(encoding="utf-8")
    assert (check / "src" / "helper.ts").is_file()


def test_check_log_survives_second_round(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    art = tmp_path / "art"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys; sys.stderr.write('round1-unique-log\\n'); sys.exit(1)\n",
        encoding="utf-8",
    )
    n = {"fix": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
                "suggestedVerify": {
                    "steps": ["device replay"],
                    "executed": False,
                    "commands": [{"command": [sys.executable, str(probe)]}],
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        n["fix"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            f"function handleFail() {{ throw e; /* {n['fix']} */ }}\n",
            encoding="utf-8",
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=art,
    )
    first_latest = json.loads((art / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    first = json.loads(Path(first_latest["path"]).read_text(encoding="utf-8"))
    refs = [c.get("logRef") for c in (first.get("checks") or []) if c.get("logRef")]
    assert refs
    log_path = Path(refs[0])
    assert log_path.is_file()
    assert "round1-unique-log" in log_path.read_text(encoding="utf-8", errors="replace")

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=art,
    )
    assert log_path.is_file(), "round-1 logRef must survive a later prepare_workspace"
    assert "round1-unique-log" in log_path.read_text(encoding="utf-8", errors="replace")


def test_partially_applied_old_patch_is_not_a_replacement(tmp_path: Path):
    import hashlib
    import subprocess

    from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, PatchFile, PatchSet
    from bugfix_platform.agents.analyst.attempt_store import save_attempt

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    original_a = _SNIPPET + "\n"
    original_h = "export const h = 0;\n"
    applied_a = "function handleFail() { throw e; }\n"
    (work / "src" / "a.ts").write_text(applied_a, encoding="utf-8")
    (work / "src" / "helper.ts").write_text(original_h, encoding="utf-8")
    art = tmp_path / "art"
    old = PatchSet(
        patchSetId="oldpatch",
        delivery="candidate",
        patches=[
            PatchFile(
                path="src/a.ts",
                kind="modify",
                digest=hashlib.sha256(applied_a.encode("utf-8")).hexdigest()[:16],
                archivePath=str(tmp_path / "old-a.diff"),
            ),
            PatchFile(
                path="src/helper.ts",
                kind="modify",
                digest=hashlib.sha256(b"export const h = 1;\n").hexdigest()[:16],
                archivePath=str(tmp_path / "old-h.diff"),
            ),
        ],
    )
    save_attempt(
        art,
        AttemptRecord.model_validate(
            {
                "schemaVersion": REPAIR_SCHEMA_VERSION,
                "attemptId": "a0",
                "defectId": "D1",
                "execution": "completed",
                "resolution": "patch_produced",
                "patchDelivery": "candidate",
                "patchSet": old.model_dump(),
            }
        ),
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "finish helper", "steps": [], "targetFiles": ["src/helper.ts"]},
                "localization": _loc({"snippet": "function handleFail() { throw e; }"}),
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "helper.ts").write_text(
            "export const h = 1;\n", encoding="utf-8"
        )
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; /* continue */ }\n", encoding="utf-8"
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=art,
    )
    latest = json.loads((art / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    patch = attempt.get("patchSet") or {}
    assert patch.get("replaces") in (None, ""), "partial/unknown must not claim full replacement"
    assert patch.get("baselineDigest") or "snapshot" in (patch.get("summary") or "").lower() or patch.get("baselineHead") is not None
    bundle = Path((attempt.get("patchSet") or {}).get("bundlePath") or report_path(attempt))
    assert bundle.is_file()
    current = tmp_path / "current"
    current.mkdir()
    (current / "src").mkdir()
    (current / "src" / "a.ts").write_text(applied_a, encoding="utf-8")
    (current / "src" / "helper.ts").write_text(original_h, encoding="utf-8")
    proc = subprocess.run(
        ["git", "apply", "--check", str(bundle)],
        cwd=current,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    original = tmp_path / "original"
    original.mkdir()
    (original / "src").mkdir()
    (original / "src" / "a.ts").write_text(original_a, encoding="utf-8")
    (original / "src" / "helper.ts").write_text(original_h, encoding="utf-8")
    proc_old = subprocess.run(
        ["git", "apply", "--check", str(bundle)],
        cwd=original,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc_old.returncode != 0, "new patch must not be a complete replacement on the original baseline"


def report_path(attempt: dict) -> str:
    files = (attempt.get("patchSet") or {}).get("patches") or []
    if files:
        return str(files[0].get("archivePath") or "")
    return ""


def test_report_includes_checks_logs_and_remaining_steps(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys; sys.stderr.write('camera_disconnected not handled\\n'); sys.exit(1)\n",
        encoding="utf-8",
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
                "suggestedVerify": {
                    "steps": ["replay on device", "confirm toast"],
                    "executed": False,
                    "commands": [{"command": [sys.executable, str(probe)]}],
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    ticket = report.tickets[0]
    commands = ticket.suggestedVerify.commands or []
    assert commands, "main report must carry executed checks"
    assert any(c.get("result") == "failed" or c.get("logRef") for c in commands)
    md = (tmp_path / "art" / "analysis-report.md").read_text(encoding="utf-8")
    assert "camera_disconnected" in md or "failed" in md.lower()
    assert "replay on device" in md or "confirm toast" in md
    assert "log" in md.lower() or any(c.get("logRef") and str(c.get("logRef")) in md for c in commands)


def test_retry_pass_sets_verify_status_from_final_candidate(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    art = tmp_path / "art"
    flag = tmp_path / "round.txt"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from pathlib import Path\n"
        f"flag = Path({str(flag)!r})\n"
        "if not flag.exists():\n"
        "    flag.write_text('1', encoding='utf-8')\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    n = {"fix": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
                "suggestedVerify": {
                    "steps": ["replay"],
                    "executed": False,
                    "commands": [{"command": [sys.executable, str(probe)]}],
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        n["fix"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        if n["fix"] >= 2:
            Path(req.worktree_path, "src", "helper.ts").write_text(
                "export function report(e) { return e; }\n", encoding="utf-8"
            )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=art,
    )
    assert n["fix"] == 2
    assert report.tickets[0].outcome == "patch_ready"
    assert report.tickets[0].verifyStatus == "passed"
    commands = report.tickets[0].suggestedVerify.commands or []
    assert any(c.get("result") == "failed" for c in commands)
    assert any(c.get("result") == "passed" for c in commands)
    digests = {c.get("candidateDigest") for c in commands if c.get("candidateDigest")}
    assert len(digests) >= 2


def test_report_records_semantic_review_conclusion(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow so toast can show", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    notes = report.tickets[0].localization.notes or ""
    latest = json.loads((tmp_path / "art" / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    premise = str((attempt.get("editDecision") or {}).get("executionPremise") or "")
    combined = f"{notes} {premise}"
    assert "not executed" in combined.lower() or "未执行" in combined
    assert "keep the error visible" not in combined.lower()


def test_check_log_uses_saved_attempt_id(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text("import sys; sys.stderr.write('x\\n'); sys.exit(1)\n", encoding="utf-8")

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
                "suggestedVerify": {
                    "steps": [],
                    "executed": False,
                    "commands": [{"command": [sys.executable, str(probe)]}],
                },
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    latest = json.loads((tmp_path / "art" / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt_id = str(latest.get("attemptId") or "")
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    assert attempt.get("attemptId") == attempt_id
    refs = [c.get("logRef") for c in (attempt.get("checks") or []) if c.get("logRef")]
    assert refs
    assert attempt_id and attempt_id in str(refs[0]).replace("\\", "/")


def _patch_attempt(*, digest: str, checks: list) -> object:
    from bugfix_contracts.repair import (
        REPAIR_SCHEMA_VERSION,
        AttemptRecord,
        PatchFile,
        PatchSet,
        VerificationRun,
    )

    return AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D1",
        execution="completed",
        resolution="patch_produced",
        patchDelivery="candidate",
        patchSet=PatchSet(
            patchSetId="p-final",
            delivery="candidate",
            patches=[
                PatchFile(
                    path="src/a.ts",
                    kind="modify",
                    digest=digest,
                    archivePath="archive/a.diff",
                )
            ],
        ),
        checks=[
            item if isinstance(item, VerificationRun) else VerificationRun.model_validate(item)
            for item in checks
        ],
    )


def test_final_candidate_mixed_checks_are_not_passed():
    from bugfix_platform.agents.analyst.run import _attach_checks_to_entry

    attempt = _patch_attempt(
        digest="final-digest",
        checks=[
            {
                "command": ["compile"],
                "result": "failed",
                "exitCode": 1,
                "coverage": "build",
                "candidateDigest": "aabbccddeeff0011",
            },
            {
                "command": ["pytest"],
                "result": "passed",
                "exitCode": 0,
                "coverage": "unit",
                "candidateDigest": "aabbccddeeff0011",
            },
        ],
    )
    # digest of the PatchSet is computed from path+digest+kind, not the literal above;
    # stamp both checks with the real final digest after construction.
    from bugfix_platform.agents.analyst.run import _patchset_digest

    digest = _patchset_digest(attempt.patchSet)
    attempt = attempt.model_copy(
        update={
            "checks": [
                run.model_copy(update={"candidateDigest": digest}) for run in attempt.checks
            ]
        }
    )
    entry = _attach_checks_to_entry(
        {"suggestedVerify": {"steps": [], "executed": False}, "verifyStatus": "skipped"},
        attempt,
    )
    assert entry["verifyStatus"] != "passed"
    assert entry["verifyStatus"] == "failed"


def test_unmatched_final_candidate_does_not_reuse_old_checks():
    from bugfix_platform.agents.analyst.run import _attach_checks_to_entry, _patchset_digest

    attempt = _patch_attempt(
        digest="new-file",
        checks=[
            {
                "command": ["pytest"],
                "result": "passed",
                "exitCode": 0,
                "coverage": "unit",
                "candidateDigest": "old-candidate",
            }
        ],
    )
    assert _patchset_digest(attempt.patchSet) != "old-candidate"
    entry = _attach_checks_to_entry(
        {"suggestedVerify": {"steps": [], "executed": False}, "verifyStatus": "skipped"},
        attempt,
    )
    assert entry["verifyStatus"] != "passed"
    assert entry["verifyStatus"] == "skipped"


def test_extracted_snippet_with_wrong_root_cause_does_not_enter_fix(tmp_path: Path):
    from bugfix_platform.sdk.analyze import _merge_with_routed, parse_analyze_payload

    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    called = {"n": 0}
    raw = (
        "```json\n"
        '{"outcome":"plan_only","rootCause":{"summary":"WebSocket heartbeat timeout in gateway",'
        '"ruledOut":[],"openQuestions":[]},"proposedFix":{"summary":"increase ping interval","steps":[],'
        '"targetFiles":["src/a.ts"]},"localization":{"candidates":[{"repoPath":".","path":"src/a.ts",'
        '"symbol":"handleFail","why":"name hit","source":"sdk"}],"notes":""},"confidence":"medium"}\n'
        "```"
    )

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        parsed = parse_analyze_payload(raw)
        payload = _merge_with_routed(
            req.routed,
            parsed or {},
            work_dir=req.work_dir,
            apply_fix=True,
        )
        cand = (payload.get("localization") or {}).get("candidates") or []
        assert cand and (cand[0].get("snippet") or ""), "auto-extract may locate the symbol"
        return AnalyzeResult(ok=True, source="sdk", payload=payload)

    def fake_fix(_req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(ok=True, source="sdk", payload={"outcome": "patch_ready"})

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


def test_passed_checks_with_failed_review_are_not_candidate(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    (work / "src" / "a.ts").write_text(_SNIPPET + "\n", encoding="utf-8")
    n = {"fix": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
                **req.routed,
                "outcome": "plan_only",
                "rootCause": {
                    "summary": "handleFail swallows camera errors",
                    "ruledOut": [],
                    "openQuestions": [],
                },
                "proposedFix": {"summary": "rethrow so toast can show", "steps": [], "targetFiles": ["src/a.ts"]},
                "localization": _loc(),
            },
        )

    def fake_fix(req: FixRequest) -> FixResult:
        n["fix"] += 1
        Path(req.worktree_path, "src", "a.ts").write_text(
            "function handleFail() { throw e; }\n", encoding="utf-8"
        )
        return FixResult(
            ok=True,
            source="sdk",
            payload={
                "outcome": "patch_ready",
                "semanticReview": "change does not restore toast; retry path still swallowed",
                "semanticReviewStatus": "failed",
                "semanticReviewExecuted": True,
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
        artifact_dir=tmp_path / "art",
    )
    assert n["fix"] >= 1
    assert report.tickets[0].outcome != "patch_ready"
    latest = json.loads((tmp_path / "art" / "defects" / "D1" / "latest.json").read_text(encoding="utf-8"))
    attempt = json.loads(Path(latest["path"]).read_text(encoding="utf-8"))
    assert attempt.get("patchDelivery") != "candidate"
    premise = str((attempt.get("editDecision") or {}).get("executionPremise") or "")
    notes = report.tickets[0].localization.notes or ""
    assert "retry path still swallowed" in f"{premise} {notes}"
