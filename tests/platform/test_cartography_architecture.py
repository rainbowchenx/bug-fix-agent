"""Agent-2 architecture map + match confidence (A3/A4)."""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.agents.cartographer.architecture import map_architecture
from bugfix_platform.agents.cartographer.detect import (
    detect_cartography_profile,
    discover_repo_roots,
)
from bugfix_platform.agents.cartographer.match import (
    MAX_CANDIDATES,
    filter_existing_candidates,
    match_tickets,
)
from bugfix_contracts import DefectBatch
from bugfix_contracts.code_knowledge import Architecture, MatchCandidate
from bugfix_contracts.defect_batch import BatchTicket

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "test" / "fixtures" / "repos"


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


def test_electron_architecture_roles():
    knowledge = run_cartographer(
        work_dir=FIXTURES / "electron",
        defect_batch=_batch_with_module(),
        cartography_mode="heuristic",
        cartography_profile="electron_node",
    )
    assert knowledge.cartographyProfile == "electron_node"
    roles = {m.role for m in knowledge.architecture.modules}
    assert "main" in roles
    assert "preload" in roles
    assert "renderer" in roles
    assert knowledge.architecture.entryPoints
    assert any("web/src/main.ts" in ep.replace("\\", "/") for ep in knowledge.architecture.entryPoints)


def test_map_architecture_device_web_capability():
    work = FIXTURES / "device-web"
    roots = discover_repo_roots(work)
    mapped = map_architecture(work, roots, "device_web")
    roles = {m.role for m in mapped.modules}
    assert "device_capability" in roles
    assert "device_bridge" in roles
    assert any("main-pc" in ep for ep in mapped.entry_points)
    assert any("main-mobile" in ep for ep in mapped.entry_points)
    route_ids = {m.id for m in mapped.modules if m.role == "route_module"}
    assert {"Config", "Preview"} <= route_ids
    assert any(i.startswith("Config.") and "snap" in i.lower() for i in route_ids), route_ids


def test_auto_dependencies_fill_tech_stack(tmp_path: Path):
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps(
            {
                "name": "web5.0-framework",
                "autoDependencies": {
                    "hui-intl": "3.1.9",
                    "@hc-ui/common": "3.0.2",
                    "@hc-ui/device": "3.0.1",
                },
            }
        ),
        encoding="utf-8",
    )
    _profile, _hints, tech = detect_cartography_profile(work, discover_repo_roots(work))
    assert "vue" in tech["frameworks"]
    assert "hui-intl" in tech["frameworks"]
    assert any(x.startswith("@hc-ui/") for x in tech["frameworks"])


def test_map_architecture_device_web_nested_service_path(tmp_path: Path):
    """peitao: 能力对象埋在 src/common/vue/service/device.js（多一层 vue/）。"""
    work = tmp_path / "repo"
    (work / "src" / "common" / "vue" / "service").mkdir(parents=True)
    (work / "src" / "main-pc.js").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "main-mobile.js").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "common" / "vue" / "service" / "device.js").write_text(
        "export default { bSupportWiper: false }\n", encoding="utf-8"
    )
    (work / "package.json").write_text(json.dumps({"name": "web5.0-framework"}), encoding="utf-8")

    mapped = map_architecture(work, discover_repo_roots(work), "device_web")
    caps = [m for m in mapped.modules if m.role == "device_capability"]
    assert caps, [m.model_dump() for m in mapped.modules]
    assert caps[0].path.replace("\\", "/").endswith("vue/service/device.js")


def test_map_architecture_micro_frontend_empty_shell_falls_back():
    """camera: root-application.js 是 0 字节空壳，宿主在仓外 → 退回主引导文件。"""
    work = FIXTURES / "micro-frontend-in-repo"
    mapped = map_architecture(work, discover_repo_roots(work), "micro_frontend")
    roles = {m.role for m in mapped.modules}
    assert {"shell", "micro_app", "shared_kernel"} <= roles
    assert mapped.entry_points, "empty shell must still yield an assembly point"
    shell = next(m for m in mapped.modules if m.role == "shell")
    assert "root-application.js is empty" in (shell.notes or "")
    apps = {m.id for m in mapped.modules if m.role == "micro_app"}
    assert {"Preview", "Playback", "Portal"} <= apps


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
    assert matched[0].confidence in {"low", "medium", "high"}
    # ≥2 path hits may be high even without CodeGraph capability.
    if len(matched[0].candidates) >= 2:
        assert matched[0].confidence == "high"
    assert all(c.source == "grep" for c in matched[0].candidates)

    filtered = filter_existing_candidates(work, matched, code_graph=False)
    assert len(filtered[0].candidates) <= MAX_CANDIDATES


def test_confidence_high_without_codegraph_capability():
    from bugfix_platform.agents.cartographer.match import _score_confidence

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
    two_grep = [
        MatchCandidate(path="src/a.ts", why="g", source="grep"),
        MatchCandidate(path="src/b.ts", why="g", source="grep"),
    ]
    conf = _score_confidence(two_grep, code_graph=False, ticket=ticket)
    assert conf == "high"

    one_cg = [MatchCandidate(path="src/a.ts", why="cg", source="codegraph")]
    assert _score_confidence(one_cg, code_graph=False, ticket=ticket) == "high"


def test_device_web_chinese_ticket_does_not_fill_entry_points():
    """无路径 token 时不得用 dual-entry 把 Router/main 填成票候选。"""
    work = FIXTURES / "device-web"
    roots = discover_repo_roots(work)
    mapped = map_architecture(work, roots, "device_web")
    architecture = Architecture(
        summary=mapped.summary,
        entryPoints=mapped.entry_points,
        modules=mapped.modules,
    )
    ticket = BatchTicket(
        defectId="OSD1",
        title="[基本功能检查表-按前端区分] 抓拍OSD设置时拖动osd消失",
        pool="strict",
        expectQuality="explicit",
        testModule="基本功能检查表-按前端区分",
        titleTag="基本功能检查表-按前端区分",
        intent="ui_layout",
    )
    matched = match_tickets(
        work,
        roots,
        [ticket],
        profile="device_web",
        architecture=architecture,
        bindings=mapped.bindings,
    )
    paths = [c.path.replace("\\", "/") for c in matched[0].candidates]
    assert not any(p.endswith("Router/mobile.js") for p in paths), paths
    assert not any(p.endswith("Router/pc.js") for p in paths), paths
    assert not any(p.endswith("main-mobile.js") for p in paths), paths
    assert not any(p.endswith("main-pc.js") for p in paths), paths
    assert matched[0].confidence == "low"
    assert matched[0].gap == "no_path_token_overlap"


def test_device_web_capability_still_hits_device_js():
    work = FIXTURES / "device-web"
    roots = discover_repo_roots(work)
    mapped = map_architecture(work, roots, "device_web")
    architecture = Architecture(
        summary=mapped.summary,
        entryPoints=mapped.entry_points,
        modules=mapped.modules,
    )
    ticket = BatchTicket(
        defectId="DW1",
        title="雨刷按钮灰掉无法使用",
        pool="strict",
        expectQuality="explicit",
        testModule="预览",
        titleTag="雨刷",
        intent="logic",
    )
    matched = match_tickets(
        work,
        roots,
        [ticket],
        profile="device_web",
        architecture=architecture,
        bindings=mapped.bindings,
    )
    paths = [c.path.replace("\\", "/") for c in matched[0].candidates]
    assert any(p.endswith("device.js") for p in paths), paths


def test_code_cartography_skill_present():
    from bugfix_platform.sdk.skills import list_package_skill_names

    assert "code-cartography" in list_package_skill_names()


def test_attach_spec_pointers_appends_without_replacing_notes():
    from bugfix_contracts.code_knowledge import ArchModule, SpecEntry
    from bugfix_platform.agents.cartographer.architecture import attach_spec_pointers

    mods = [
        ArchModule(id="HCBVideo", path="hct/src/HCBVideo", notes="报警回放 UI"),
        ArchModule(id="HCBPortal", path="hct/src/HCBPortal"),
        ArchModule(id="other", path="src/other", notes="keep me"),
    ]
    entries = [
        SpecEntry(path="hct/.trellis/spec/src/HCBVideo/frontend", kind="doc_ref"),
        SpecEntry(path="hct/.trellis/spec/src/HCBPortal/frontend", kind="doc_ref"),
        SpecEntry(path="hct/CLAUDE.md", kind="guide"),
    ]
    attach_spec_pointers(mods, entries)
    assert "报警回放 UI" in (mods[0].notes or "")
    assert "spec:" in (mods[0].notes or "")
    assert "HCBVideo/frontend" in (mods[0].notes or "")
    assert mods[1].notes and "HCBPortal/frontend" in mods[1].notes
    assert mods[2].notes == "keep me"


def test_cartographer_indexes_trellis_and_points_modules(tmp_path: Path):
    work = tmp_path / "app"
    (work / "src" / "HCBVideo").mkdir(parents=True)
    (work / "src" / "HCBVideo" / "vue.app.js").write_text("export {}\n", encoding="utf-8")
    (work / "package.json").write_text(
        json.dumps({"name": "hct", "dependencies": {"single-spa": "5"}}),
        encoding="utf-8",
    )
    spec = work / ".trellis" / "spec" / "src" / "HCBVideo" / "frontend"
    spec.mkdir(parents=True)
    (spec / "README.md").write_text("规范正文\n", encoding="utf-8")

    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch_with_module(),
        cartography_mode="heuristic",
        cartography_profile="micro_frontend",
    )
    assert knowledge.specAtlas.frameworkId == "trellis"
    refs = [e.path.replace("\\", "/") for e in knowledge.specAtlas.entries if e.kind == "doc_ref"]
    assert any("HCBVideo/frontend" in p for p in refs), refs
    video = next(m for m in knowledge.architecture.modules if m.id == "HCBVideo")
    assert "from=" in (video.notes or "") or "entry=" in (video.notes or "") or video.notes
    assert "spec:" in (video.notes or "")
    assert "规范正文" not in json.dumps(knowledge.specAtlas.model_dump(), ensure_ascii=False)


def test_attach_spec_pointers_is_idempotent():
    from bugfix_contracts.code_knowledge import ArchModule, SpecEntry
    from bugfix_platform.agents.cartographer.architecture import attach_spec_pointers

    mods = [ArchModule(id="HCBVideo", path="src/HCBVideo", notes="ui")]
    entries = [SpecEntry(path=".trellis/spec/src/HCBVideo/frontend", kind="doc_ref")]
    attach_spec_pointers(mods, entries)
    once = mods[0].notes
    attach_spec_pointers(mods, entries)
    assert mods[0].notes == once
