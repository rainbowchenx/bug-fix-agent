"""Catalog files are not loci; ticket variant drops opposite-end exclusive paths."""

from __future__ import annotations

from pathlib import Path

from bugfix_contracts.code_knowledge import Architecture, ArchModule, DefectCodeMatch, MatchCandidate
from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.agents.cartographer.architecture import map_architecture
from bugfix_platform.agents.cartographer.detect import discover_repo_roots
from bugfix_platform.agents.cartographer.match import (
    filter_existing_candidates,
    match_tickets,
    ticket_variant,
)


def _cand(*paths: str) -> list[DefectCodeMatch]:
    return [
        DefectCodeMatch(
            defectId="D1",
            candidates=[
                MatchCandidate(path=p, why="hit", source="grep") for p in paths
            ],
            confidence="medium",
        )
    ]


def test_ticket_variant_fail_open_and_markers():
    pc = BatchTicket(
        defectId="1",
        title="[web端] 预览残留",
        pool="strict",
        expectQuality="explicit",
    )
    mobile = BatchTicket(
        defectId="2",
        title="手机端 OSD 消失",
        pool="strict",
        expectQuality="explicit",
        testModule="H5",
    )
    both = BatchTicket(
        defectId="3",
        title="PC 和手机都异常",
        pool="strict",
        expectQuality="explicit",
    )
    silent = BatchTicket(
        defectId="4",
        title="雨刷按钮灰掉",
        pool="strict",
        expectQuality="explicit",
    )
    portal = BatchTicket(
        defectId="5",
        title="Portal 登录失败",
        pool="strict",
        expectQuality="explicit",
        testModule="Portal",
    )
    assert ticket_variant(pc) == "pc"
    assert ticket_variant(mobile) == "mobile"
    assert ticket_variant(both) is None
    assert ticket_variant(silent) is None
    assert ticket_variant(portal) is None


def test_filter_drops_catalog_roles(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "root-application.js").write_text("export function boot() {}\n", encoding="utf-8")
    (src / "index.asp").write_text("<!-- host -->\n", encoding="utf-8")
    (src / "Router").mkdir()
    (src / "Router" / "mobile.js").write_text("export default [];\n", encoding="utf-8")
    (src / "Preview.vue").write_text("<script>export default {}</script>\n", encoding="utf-8")
    arch = Architecture(
        entryPoints=["src/main-pc.js"],
        modules=[
            ArchModule(id="shell", path="src/root-application.js", role="shell"),
            ArchModule(id="host", path="src/index.asp", role="host"),
            ArchModule(id="rt", path="src/Router/mobile.js", role="route_table"),
            ArchModule(id="app", path="src/Preview.vue", role="route_module"),
        ],
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _cand(
            "src/Preview.vue",
            "src/root-application.js",
            "src/Router/mobile.js",
        ),
        architecture=arch,
    )
    assert [c.path.replace("\\", "/") for c in filtered[0].candidates] == [
        "src/Preview.vue"
    ]


def test_filter_pc_ticket_drops_mobile_exclusive(tmp_path: Path):
    preview = tmp_path / "src" / "Preview"
    (preview / "mobile").mkdir(parents=True)
    (preview / "view").mkdir()
    (preview / "mobile" / "index.vue").write_text(
        "<script>export default { methods: { play() {} } }</script>\n", encoding="utf-8"
    )
    (preview / "view" / "index.vue").write_text(
        "<script>export default { methods: { play() {} } }</script>\n", encoding="utf-8"
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _cand("src/Preview/mobile/index.vue", "src/Preview/view/index.vue"),
        variant_by_id={"D1": "pc"},
    )
    assert [c.path.replace("\\", "/") for c in filtered[0].candidates] == [
        "src/Preview/view/index.vue"
    ]


def test_filter_keeps_shared_and_ipc_controller(tmp_path: Path):
    (tmp_path / "src" / "Common" / "service").mkdir(parents=True)
    (tmp_path / "electron" / "controller" / "device").mkdir(parents=True)
    (tmp_path / "src" / "Common" / "service" / "device.js").write_text(
        "export default { bSupportWiper: false }\n", encoding="utf-8"
    )
    (tmp_path / "electron" / "controller" / "device" / "index.ts").write_text(
        "export function handleDevice() {}\n", encoding="utf-8"
    )
    arch = Architecture(
        modules=[
            ArchModule(
                id="ipc:device",
                path="electron/controller/device",
                role="ipc_domain",
            )
        ]
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _cand(
            "src/Common/service/device.js",
            "electron/controller/device/index.ts",
        ),
        architecture=arch,
        variant_by_id={"D1": "pc"},
    )
    kept = {c.path.replace("\\", "/") for c in filtered[0].candidates}
    assert kept == {
        "src/Common/service/device.js",
        "electron/controller/device/index.ts",
    }


def test_nested_router_is_route_table_and_not_a_locus():
    work = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "repos" / "device-web"
    roots = discover_repo_roots(work)
    mapped = map_architecture(work, roots, "device_web")
    tables = [
        (m.path or "").replace("\\", "/")
        for m in mapped.modules
        if m.role == "route_table"
    ]
    assert any(p.endswith("Router/device/mobile.js") for p in tables), tables
    architecture = Architecture(
        summary=mapped.summary,
        entryPoints=mapped.entry_points,
        modules=mapped.modules,
    )
    ticket = BatchTicket(
        defectId="IPC1",
        title="[web端] device IPC 上报失败",
        pool="strict",
        expectQuality="explicit",
        testModule="device",
        titleTag="device",
        intent="logic",
    )
    matched = match_tickets(
        work,
        roots,
        [ticket],
        profile="device_web",
        architecture=architecture,
    )
    paths = [c.path.replace("\\", "/") for c in matched[0].candidates]
    assert not any(p.endswith("Router/device/mobile.js") for p in paths), paths
    assert not any(p.endswith("Router/mobile.js") for p in paths), paths


def test_static_path_ranks_below_src(tmp_path: Path):
    from tests.helpers import ensure_git_repo

    ensure_git_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "static").mkdir()
    (tmp_path / "src" / "overlay.js").write_text(
        "export function overlay() {}\n", encoding="utf-8"
    )
    (tmp_path / "static" / "overlay.js").write_text(
        "export function overlay() {}\n", encoding="utf-8"
    )
    ticket = BatchTicket(
        defectId="1",
        title="overlay broken",
        pool="strict",
        expectQuality="explicit",
        titleTag="overlay",
        testModule="overlay",
        intent="ui_layout",
    )
    matched = match_tickets(tmp_path, discover_repo_roots(tmp_path), [ticket])
    paths = [c.path.replace("\\", "/") for c in matched[0].candidates]
    assert paths, paths
    assert paths[0].endswith("src/overlay.js")
    assert not paths[0].replace("\\", "/").startswith("static/")
