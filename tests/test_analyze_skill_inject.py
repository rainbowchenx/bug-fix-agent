"""Agent-3 analyze skill injection shares overlay dirs with Agent-2."""

from __future__ import annotations

from pathlib import Path

from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.contracts import CodeKnowledge, DefectBatch
from bugfix_agent.sdk.analyze import AnalyzeRequest, AnalyzeResult
from bugfix_agent.sdk.skill_inject import (
    analyze_skills_addon,
    discover_analyze_skills,
    discover_cartography_skills,
)


def _write_skill(folder: Path, name: str, *, profiles: str | None, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    profile_line = f"profiles: {profiles}\n" if profiles is not None else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: guide for {name}\n{profile_line}---\n\n{body}\n",
        encoding="utf-8",
    )


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
                    "title": "[回放] preview",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "testModule": "回放",
                    "titleTag": "回放",
                    "intent": "ui_layout",
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
            "cartographyProfile": "electron_node",
            "defectCodeMatches": [
                {
                    "defectId": "D1",
                    "candidates": [
                        {
                            "repoPath": ".",
                            "path": "src/preview.ts",
                            "why": "token",
                            "source": "heuristic",
                        }
                    ],
                    "confidence": "medium",
                }
            ],
        }
    )


def test_bugfix_profile_loads_for_both_agents(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".bugfix" / "skills" / "hc-layout",
        "hc-layout",
        profiles="bugfix",
        body="回放 → packages/playback",
    )
    _write_skill(
        work / ".bugfix" / "skills" / "only-analyze",
        "only-analyze",
        profiles="analyze",
        body="验证用 pnpm --filter player test",
    )
    _write_skill(
        work / ".bugfix" / "skills" / "only-map",
        "only-map",
        profiles="cartography",
        body="先看 packages/player",
    )
    carto = {s.name for s in discover_cartography_skills(work)}
    analyze = {s.name for s in discover_analyze_skills(work)}
    assert "hc-layout" in carto and "hc-layout" in analyze
    assert "only-analyze" in analyze and "only-analyze" not in carto
    assert "only-map" in carto and "only-map" not in analyze


def test_unprofiled_bugfix_dir_applies_to_both(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".bugfix" / "skills" / "line-defaults",
        "line-defaults",
        profiles=None,
        body="不要扫 packages/legacy",
    )
    assert any(s.name == "line-defaults" for s in discover_cartography_skills(work))
    assert any(s.name == "line-defaults" for s in discover_analyze_skills(work))


def test_analyze_addon_puts_overlay_first(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".bugfix" / "skills" / "hc-test",
        "hc-test",
        profiles="analyze",
        body="单测在 tests/unit，不要跑 e2e 当定位。",
    )
    skills = discover_analyze_skills(work)
    text = analyze_skills_addon(skills)
    assert "HIGHEST PRIORITY" in text
    assert "tests/unit" in text
    assert text.find("hc-test") < text.find("Package SOP")


def test_run_analyst_binds_and_forwards_overlay(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    extra = tmp_path / "line-skills"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    (work / "src").mkdir()
    (work / "src" / "preview.ts").write_text("export {}\n", encoding="utf-8")
    _write_skill(
        extra / "hc-verify",
        "hc-verify",
        profiles="analyze",
        body="验证：pnpm --filter @acme/player test",
    )
    seen: dict[str, tuple[str, ...]] = {}

    def fake_analyze(req: AnalyzeRequest) -> AnalyzeResult:
        seen["names"] = tuple(s.name for s in req.injected_skills)
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
                    "targetFiles": ["src/preview.ts"],
                },
            },
        )

    report = run_analyst(
        work_dir=work,
        defect_batch=_batch(),
        code_knowledge=_knowledge(work),
        extra_skill_dirs=[extra],
        analyze_fn=fake_analyze,
    )
    assert "hc-verify" in report.boundSkills
    assert report.boundSkills.index("hc-verify") < report.boundSkills.index(
        "systematic-debugging"
    )
    assert seen["names"][0] == "hc-verify"
