"""Agent-2 architecture map + match confidence (A3/A4)."""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.agents.cartographer.architecture import map_architecture
from bugfix_agent.agents.cartographer.detect import discover_repo_roots
from bugfix_agent.agents.cartographer.match import (
    MAX_CANDIDATES,
    filter_existing_candidates,
    match_tickets,
)
from bugfix_agent.contracts import DefectBatch
from bugfix_agent.contracts.code_knowledge import DefectCodeMatch, MatchCandidate
from bugfix_agent.contracts.defect_batch import BatchTicket


def _batch_with_module() -> DefectBatch:
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
                    "clusterId": "hc::回放::_untagged::ui_layout",
                    "observed": "glitch",
                    "expected": "smooth",
                    "steps": "open preview",
                }
            ],
        }
    )


def test_electron_architecture_roles(tmp_path: Path):
    work = tmp_path / "app"
    (work / "electron").mkdir(parents=True)
    (work / "src" / "renderer").mkdir(parents=True)
    (work / "package.json").write_text(
        json.dumps(
            {
                "name": "e",
                "main": "electron/main.ts",
                "dependencies": {"electron": "30"},
            }
        ),
        encoding="utf-8",
    )
    (work / "electron" / "main.ts").write_text("export {}\n", encoding="utf-8")
    (work / "electron" / "preload.ts").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "renderer" / "App.tsx").write_text("export {}\n", encoding="utf-8")

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch_with_module(),
        cartography_mode="heuristic",
    )
    assert knowledge.cartographyProfile == "electron_node"
    roles = {m.role for m in knowledge.architecture.modules}
    assert "main" in roles
    assert "preload" in roles or "renderer" in roles
    assert knowledge.architecture.entryPoints
    assert any("main" in ep for ep in knowledge.architecture.entryPoints)


def test_map_architecture_device_web_bridge(tmp_path: Path):
    work = tmp_path / "dw"
    (work / "bridge").mkdir(parents=True)
    (work / "package.json").write_text(json.dumps({"name": "dw"}), encoding="utf-8")
    (work / "bridge" / "jsbridge.ts").write_text("export {}\n", encoding="utf-8")
    roots = discover_repo_roots(work)
    summary, entries, modules = map_architecture(work, roots, "device_web")
    assert "bridge" in summary.lower() or modules
    assert any(m.role == "device_bridge" for m in modules)
    assert entries


def test_match_caps_candidates_and_confidence(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src").mkdir(parents=True)
    for i in range(6):
        (work / "src" / f"preview-extra-{i}.ts").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export {}\n", encoding="utf-8")
    (work / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")

    roots = discover_repo_roots(work)
    ticket = BatchTicket(
        defectId="1",
        title="preview player broken",
        pool="strict",
        expectQuality="explicit",
        titleTag="preview",
        testModule="player",
        intent="ui_layout",
    )
    matched = match_tickets(work, roots, [ticket], code_graph=False)
    assert len(matched[0].candidates) <= MAX_CANDIDATES
    assert matched[0].confidence in {"low", "medium"}
    assert matched[0].confidence != "high"  # no CodeGraph
    assert all(c.source == "grep" for c in matched[0].candidates)

    filtered = filter_existing_candidates(work, matched, code_graph=False)
    assert len(filtered[0].candidates) <= MAX_CANDIDATES


def test_confidence_codegraph_can_be_high_when_enabled():
    ticket = BatchTicket(
        defectId="1",
        title="t",
        pool="strict",
        expectQuality="explicit",
        titleTag="a",
        testModule="b",
        intent="ui_layout",
        clusterId="c",
    )
    matches = [
        DefectCodeMatch(
            defectId="1",
            title="t",
            candidates=[
                MatchCandidate(path="src/a.ts", why="cg", source="codegraph"),
            ],
            confidence="low",
        )
    ]
    # Without real files filter keeps empty → low; score path via match helper:
    from bugfix_agent.agents.cartographer.match import _score_confidence

    conf = _score_confidence(matches[0].candidates, code_graph=True, ticket=ticket)
    assert conf == "high"


def test_code_cartography_skill_present():
    from bugfix_agent.sdk.skills import list_package_skill_names

    assert "code-cartography" in list_package_skill_names()
