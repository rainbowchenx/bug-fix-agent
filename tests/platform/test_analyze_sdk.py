import json
from pathlib import Path

from bugfix_platform.agents.analyst import run_analyst
from bugfix_contracts import CodeKnowledge, DefectBatch
from bugfix_platform.sdk.analyze import (
    AnalyzeRequest,
    AnalyzeResult,
    _SYSTEM_PROMPT,
    _build_prompt,
    analyze_mode_from_env,
    heuristic_analyze,
    parse_analyze_payload,
)
from bugfix_platform.workflow import run_three_agent_workflow

ROOT = Path(__file__).resolve().parents[2]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


def test_analyze_prompt_includes_architecture_map():
    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="osd overlay",
        pool="strict",
        expectQuality="explicit",
        intentRationale="小图上拖动 OSD 后消失，是叠加位置交互问题",
    )
    req = AnalyzeRequest(
        work_dir="/tmp",
        ticket=ticket,
        routed={"outcome": "plan_only", "localization": {"candidates": []}},
        cartography_profile="device_web",
        architecture={
            "summary": "Device-web dual-entry map",
            "entryPoints": ["src/main-pc.js"],
            "modules": [{"id": "Config", "path": "src/Config", "role": "route_module"}],
        },
        reading_playbook="device_web read order: split PC vs mobile",
    )
    prompt = _build_prompt(req)
    assert "Device-web dual-entry map" in prompt
    assert "src/Config" in prompt
    assert "device_web" in prompt
    assert "叠加位置交互" in prompt
    assert "follow" in _SYSTEM_PROMPT.lower()
    assert "soft-start" in _SYSTEM_PROMPT.lower() or "soft start" in _SYSTEM_PROMPT.lower()


def test_parse_analyze_payload_fence():
    text = """Here is the analysis:
```json
{"outcome":"plan_only","rootCause":{"summary":"null deref","ruledOut":[],"openQuestions":[]},"proposedFix":{"summary":"guard null","steps":["add check"],"targetFiles":["a.ts"]},"confidence":"medium"}
```
"""
    parsed = parse_analyze_payload(text)
    assert parsed is not None
    assert parsed["outcome"] == "plan_only"
    assert parsed["proposedFix"]["summary"] == "guard null"


def test_heuristic_analyze_annotates(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert analyze_mode_from_env() == "heuristic"

    from bugfix_contracts.defect_batch import BatchTicket

    ticket = BatchTicket(
        defectId="1",
        title="t",
        pool="strict",
        expectQuality="explicit",
    )
    routed = {
        "outcome": "plan_only",
        "proposedFix": {"summary": "s", "steps": [], "targetFiles": ["a.ts"]},
        "rootCause": {"summary": "pending", "ruledOut": [], "openQuestions": []},
        "localization": {"candidates": [{"repoPath": ".", "path": "a.ts"}]},
        "confidence": "medium",
        "verifyStatus": "skipped",
        "suggestedVerify": {"steps": [], "executed": False},
        "blockers": None,
        "patch": None,
    }
    result = heuristic_analyze(AnalyzeRequest(work_dir="/tmp", ticket=ticket, routed=routed))
    assert result.source == "heuristic"
    assert "heuristic mode" in " ".join(result.payload["rootCause"]["openQuestions"])


def test_analyst_uses_injected_analyze_fn(tmp_path: Path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    batch = DefectBatch.model_validate(
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
                    "title": "[回放] preview glitch",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "testModule": "回放",
                    "titleTag": "回放",
                    "intent": "ui_layout",
                    "observed": "glitch",
                    "expected": "smooth",
                    "steps": "open preview",
                }
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
            "cartographyProfile": "electron_node",
            "secondaryHints": [],
            "techStack": {"languages": ["ts"], "frameworks": ["electron"]},
            "architecture": {"summary": "mini", "entryPoints": [], "modules": []},
            "conventions": {"fromClaudeMd": [], "fromRules": []},
            "boundSkills": [],
            "specAtlas": {"frameworkId": "unknown", "entries": []},
            "capabilities": {"codeGraph": False, "runtimeVerify": False},
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/preview-player.ts",
                            "why": "token",
                            "source": "heuristic",
                        }
                    ],
                    "confidence": "medium",
                }
            ],
        }
    )

    calls = {"n": 0}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        calls["n"] += 1
        assert req.cartography_profile == "electron_node"
        assert req.architecture is not None
        return AnalyzeResult(
            ok=True,
            source="sdk",
            payload={
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
                "confidence": "high",
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=fake_analyze,
    )
    assert calls["n"] == 1
    assert report.tickets[0].rootCause.summary == "Race in preview player init"
    assert report.tickets[0].confidence == "high"
    assert "analyze=sdk" in (report.tickets[0].localization.notes or "")


def test_workflow_heuristic_analyze_mode(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    work = tmp_path / "mini"
    (work / "src").mkdir(parents=True)
    (work / "package.json").write_text(
        json.dumps({"name": "mini-hc", "version": "0.0.1", "dependencies": {"electron": "30.0.0"}}),
        encoding="utf-8",
    )
    (work / "CLAUDE.md").write_text("# Mini\nUse CodeGraph for search.\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    (work / "src" / "回放.ts").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "检索.ts").write_text("export {}\n", encoding="utf-8")

    from tests.helpers import defect_batch_from_hc1

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
    )
    assert result.ok is True
    assert result.artifacts.analysis_report is not None
    planish = [t for t in result.artifacts.analysis_report.tickets if t.outcome == "plan_only"]
    assert planish
    assert any("heuristic" in (t.localization.notes or "") for t in planish)
