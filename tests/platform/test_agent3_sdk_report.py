"""Agent-3: SDK analyze for every match-pool ticket; fix gated by --apply-fix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.sdk.analyze import (
    AnalyzeRequest,
    AnalyzeResult,
    _SYSTEM_PROMPT,
    _build_prompt,
    _merge_with_routed,
    run_claude_analyze,
)
from bugfix_platform.sdk.fix import FixRequest, FixResult
from bugfix_platform.workflow import run_three_agent_workflow


def _batch(
    work: Path,
    *,
    pool: str = "strict",
    defect_id: str = "D1",
    title: str = "[回放] preview glitch",
) -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1 if pool == "strict" else 0},
            "clusters": [],
            "tickets": [
                {
                    "defectId": defect_id,
                    "title": title,
                    "pool": pool,
                    "expectQuality": "explicit",
                    "testModule": "回放",
                    "titleTag": "回放",
                    "intent": "ui_layout",
                    "observed": "glitch",
                    "expected": "smooth",
                    "steps": "open preview",
                    "intentRationale": "预览初始化竞态",
                }
            ],
        }
    )


def _knowledge(work: Path, *, candidates: list[dict] | None) -> CodeKnowledge:
    return CodeKnowledge.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(work),
            "partial": False,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "electron_node",
            "secondaryHints": [],
            "techStack": {"languages": ["ts"], "frameworks": ["electron"]},
            "architecture": {
                "summary": "mini",
                "entryPoints": ["src/main.js"],
                "modules": [
                    {
                        "id": "router",
                        "path": "src/Router/device/mobile.js",
                        "role": "route_table",
                    }
                ],
            },
            "conventions": {"fromClaudeMd": [], "fromRules": []},
            "boundSkills": [],
            "specAtlas": {"frameworkId": "unknown", "entries": []},
            "capabilities": {"codeGraph": False, "runtimeVerify": False},
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": candidates or [],
                    "confidence": "low" if not candidates else "medium",
                    "gap": "no_path_token_overlap" if not candidates else None,
                }
            ],
        }
    )


def _mini_repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    (work / "src" / "Router").mkdir(parents=True)
    (work / "src" / "Router" / "device").mkdir()
    (work / "src" / "Router" / "device" / "mobile.js").write_text(
        "export default {};\n", encoding="utf-8"
    )
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    return work


def _plan_payload(req: AnalyzeRequest, **overrides) -> AnalyzeResult:
    payload = {
        **req.routed,
        "outcome": "plan_only",
        "rootCause": {
            "summary": "Race in preview player init",
            "ruledOut": ["network"],
            "openQuestions": [],
        },
        "proposedFix": {
            "summary": "Serialize init before play()",
            "steps": ["guard re-entry"],
            "targetFiles": ["src/preview-player.ts"],
        },
        "localization": {
            "candidates": [
                {"repoPath": ".", "path": "src/preview-player.ts", "why": "sdk", "source": "grep"}
            ],
            "notes": "followed imports",
        },
        "blockers": None,
        "confidence": "high",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": ["replay preview"], "executed": False},
        "patch": None,
    }
    payload.update(overrides)
    return AnalyzeResult(ok=True, source="sdk", payload=payload)


def test_analyst_analyzes_empty_agent2_candidates(tmp_path: Path):
    work = _mini_repo(tmp_path)
    calls: list[AnalyzeRequest] = []

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls.append(req)
        return _plan_payload(req)

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(work),
        code_knowledge=_knowledge(work, candidates=[]),
        analyze_fn=fake_analyze,
    )
    assert len(calls) == 1
    assert report.tickets[0].outcome == "plan_only"
    assert report.tickets[0].rootCause.summary == "Race in preview player init"
    assert report.applyFix is False


def test_analyst_skips_sdk_for_needs_info(tmp_path: Path):
    work = _mini_repo(tmp_path)
    calls = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls["n"] += 1
        return _plan_payload(req)

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(work, pool="needs_info"),
        code_knowledge=_knowledge(work, candidates=[]),
        analyze_fn=fake_analyze,
    )
    assert calls["n"] == 0
    assert report.tickets[0].outcome == "needs_ticket_info"


def test_sdk_without_credentials_is_other_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    work = _mini_repo(tmp_path)
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="D1", title="t", pool="strict", expectQuality="explicit"
    )
    routed = {
        "outcome": "plan_only",
        "proposedFix": {"summary": "inspect", "steps": [], "targetFiles": []},
        "rootCause": {"summary": "pending", "ruledOut": [], "openQuestions": []},
        "localization": {"candidates": [], "notes": ""},
        "confidence": "low",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": [], "executed": False},
        "blockers": None,
        "patch": None,
    }
    result = run_claude_analyze(
        AnalyzeRequest(work_dir=str(work), ticket=ticket, routed=routed)
    )
    assert result.source == "sdk_fallback"
    assert result.payload["outcome"] == "other_blocked"
    assert result.payload["blockers"]["kind"] == "other_blocked"


def test_merge_drops_missing_and_catalog_paths(tmp_path: Path):
    work = _mini_repo(tmp_path)
    routed = {
        "outcome": "plan_only",
        "proposedFix": {"summary": "inspect", "steps": [], "targetFiles": []},
        "rootCause": {"summary": "pending", "ruledOut": [], "openQuestions": []},
        "localization": {"candidates": [], "notes": "soft"},
        "confidence": "low",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": [], "executed": False},
        "blockers": None,
        "patch": None,
    }
    parsed = {
        "outcome": "plan_only",
        "rootCause": {"summary": "route table is not the bug", "ruledOut": [], "openQuestions": []},
        "proposedFix": {
            "summary": "fix preview",
            "steps": ["edit player"],
            "targetFiles": ["src/preview-player.ts"],
        },
        "localization": {
            "candidates": [
                {"repoPath": ".", "path": "src/Router/device/mobile.js", "why": "table"},
                {"repoPath": ".", "path": "src/does-not-exist.ts", "why": "hallucinated"},
                {"repoPath": ".", "path": "src/preview-player.ts", "why": "player"},
            ]
        },
        "confidence": "medium",
    }
    architecture = {
        "modules": [
            {"id": "router", "path": "src/Router/device/mobile.js", "role": "route_table"}
        ]
    }
    merged = _merge_with_routed(
        routed, parsed, work_dir=str(work), architecture=architecture, apply_fix=False
    )
    paths = [c["path"] for c in merged["localization"]["candidates"]]
    assert paths == ["src/preview-player.ts"]
    assert merged["outcome"] == "plan_only"


def test_apply_fix_false_coerces_patch_ready(tmp_path: Path):
    work = _mini_repo(tmp_path)

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return _plan_payload(req, outcome="patch_ready")

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(work),
        code_knowledge=_knowledge(
            work,
            candidates=[
                {
                    "repoPath": ".",
                    "path": "src/preview-player.ts",
                    "why": "token",
                    "source": "heuristic",
                }
            ],
        ),
        analyze_fn=fake_analyze,
        apply_fix=False,
    )
    assert report.applyFix is False
    assert report.tickets[0].outcome == "plan_only"
    assert report.tickets[0].patch is None


def test_apply_fix_off_never_calls_fix(tmp_path: Path):
    work = _mini_repo(tmp_path)
    called = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return _plan_payload(req)

    def fake_fix(req: FixRequest) -> FixResult:
        called["n"] += 1
        return FixResult(ok=True, payload={"patch": {"path": "nope.patch", "summary": "x"}})

    run_analyst(
        work_dir=work,
        defect_batch=_batch(work),
        code_knowledge=_knowledge(
            work,
            candidates=[
                {
                    "repoPath": ".",
                    "path": "src/preview-player.ts",
                    "why": "token",
                    "source": "heuristic",
                }
            ],
        ),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
    )
    assert called["n"] == 0


def test_apply_fix_on_calls_fix_and_sets_patch_ready(tmp_path: Path):
    work = _mini_repo(tmp_path)
    patch_path = tmp_path / "D1.patch"
    patch_path.write_text("diff --git a/src/preview-player.ts b/src/preview-player.ts\n", encoding="utf-8")
    calls = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        return _plan_payload(req)

    def fake_fix(req: FixRequest) -> FixResult:
        calls["n"] += 1
        assert req.ticket.defectId == "D1"
        return FixResult(
            ok=True,
            source="sdk",
            payload={
                "outcome": "patch_ready",
                "patch": {"path": str(patch_path), "summary": "guard re-entry"},
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(work),
        code_knowledge=_knowledge(
            work,
            candidates=[
                {
                    "repoPath": ".",
                    "path": "src/preview-player.ts",
                    "why": "token",
                    "source": "heuristic",
                }
            ],
        ),
        analyze_fn=fake_analyze,
        fix_fn=fake_fix,
        apply_fix=True,
    )
    assert calls["n"] == 1
    assert report.applyFix is True
    assert report.tickets[0].outcome == "patch_ready"
    assert report.tickets[0].patch is not None
    assert report.tickets[0].patch.path == str(patch_path)


def test_open_mr_without_apply_fix_fails(tmp_path: Path):
    work = _mini_repo(tmp_path)
    from tests.helpers import defect_batch_from_hc1

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
        cartography_mode="heuristic",
        open_mr=True,
        apply_fix=False,
    )
    assert result.ok is False
    assert "apply-fix" in (result.error or "").lower() or "apply_fix" in (result.error or "").lower()


def test_analyze_prompt_names_gap_and_apply_fix():
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="osd overlay",
        pool="strict",
        expectQuality="explicit",
        intentRationale="小图上拖动 OSD 后消失",
    )
    req = AnalyzeRequest(
        work_dir="/tmp",
        ticket=ticket,
        routed={
            "outcome": "unlocalized",
            "localization": {
                "candidates": [],
                "notes": "empty; gap=no_path_token_overlap",
            },
        },
        apply_fix=False,
        cartography_profile="device_web",
        architecture={"summary": "dw", "entryPoints": [], "modules": []},
        reading_playbook="split PC vs mobile",
    )
    prompt = _build_prompt(req)
    assert "no_path_token_overlap" in prompt
    assert "applyFix: false" in prompt or "applyFix=false" in prompt
    assert "empty" in _SYSTEM_PROMPT.lower() or "glob" in _SYSTEM_PROMPT.lower()
    assert "plan_only" in _SYSTEM_PROMPT
