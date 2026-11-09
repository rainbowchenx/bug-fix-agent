import json
from pathlib import Path

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_contracts import DefectBatch
from bugfix_platform.sdk.cartography import (
    CARTOGRAPHY_TOOLS,
    DISALLOWED_TOOLS,
    CartographyRequest,
    CartographyResult,
    bash_command_allowed,
    cartography_mode_from_env,
    heuristic_cartography,
    resolve_cartography_max_turns,
)
from bugfix_platform.workflow import run_three_agent_workflow

ROOT = Path(__file__).resolve().parents[2]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


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


def test_heuristic_cartography_annotates(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MODE", raising=False)
    assert cartography_mode_from_env() == "heuristic"

    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    assert "heuristic mode" in knowledge.architecture.summary
    assert knowledge.cartographyProfile == "electron_node"


def test_cartographer_uses_injected_enricher(tmp_path: Path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "x", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_enrich(req: CartographyRequest) -> CartographyResult:
        calls["n"] += 1
        data = req.baseline.model_dump()
        data["architecture"] = {
            **data["architecture"],
            "summary": "SDK thickened electron map",
            "entryPoints": ["src/main.ts"],
        }
        data["defectCodeMatches"] = [
            {
                "defectId": "D1",
                "candidates": [
                    {
                        "repoPath": ".",
                        "path": "src/preview-player.ts",
                        "why": "sdk refined",
                        "source": "grep",
                    }
                ],
                "confidence": "high",
            }
        ]
        from bugfix_contracts import validate_code_knowledge

        return CartographyResult(
            ok=True,
            knowledge=validate_code_knowledge(data),
            source="sdk",
        )

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch(),
        cartography_fn=fake_enrich,
    )
    assert calls["n"] == 1
    assert knowledge.architecture.summary == "SDK thickened electron map"
    assert knowledge.architecture.entryPoints == ["src/main.ts"]
    assert knowledge.defectCodeMatches[0].confidence == "high"


def test_workflow_cartography_heuristic(tmp_path: Path, monkeypatch):
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

    from tests.helpers import defect_batch_from_hc1

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        cartography_mode="heuristic",
        analyze_mode="heuristic",
    )
    assert result.ok is True
    assert result.artifacts.code_knowledge is not None
    assert "heuristic mode" in result.artifacts.code_knowledge.architecture.summary


def test_heuristic_cartography_direct(tmp_path: Path):
    from bugfix_contracts import validate_code_knowledge

    baseline = validate_code_knowledge(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "workDir": str(tmp_path),
            "partial": True,
            "generatedAt": "2026-01-01T00:00:00Z",
            "repoRoots": [{"path": "."}],
            "cartographyProfile": "unknown",
            "architecture": {"summary": "base", "entryPoints": [], "modules": []},
            "defectCodeMatches": [],
        }
    )
    out = heuristic_cartography(
        CartographyRequest(work_dir=str(tmp_path), defect_batch=_batch(), baseline=baseline)
    )
    assert out.source == "heuristic"
    assert "heuristic mode" in out.knowledge.architecture.summary


def test_cartography_tools_allow_bash_forbid_writes():
    assert "Bash" in CARTOGRAPHY_TOOLS
    assert "Read" in CARTOGRAPHY_TOOLS
    for blocked in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        assert blocked in DISALLOWED_TOOLS
    assert "Bash" not in DISALLOWED_TOOLS


def test_resolve_cartography_max_turns_unlimited_by_default(monkeypatch):
    monkeypatch.delenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", raising=False)
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "unlimited")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "0")
    assert resolve_cartography_max_turns() is None
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MAX_TURNS", "64")
    assert resolve_cartography_max_turns() == 64
    assert resolve_cartography_max_turns(12) == 12
    assert resolve_cartography_max_turns(0) is None


def test_bash_command_allowed_readonly_vs_mutating():
    assert bash_command_allowed("rg -n login src")[0] is True
    assert bash_command_allowed("git blame src/node/routes/login.ts")[0] is True
    assert bash_command_allowed("git push origin HEAD")[0] is False
    assert bash_command_allowed("rm -rf src")[0] is False
    assert bash_command_allowed("curl https://example.com")[0] is False
    assert bash_command_allowed("npm install lodash")[0] is False
