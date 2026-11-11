"""SDK/heuristic candidate gates: vacuum files, symbol-in-file, device_web stubs."""

from __future__ import annotations

from pathlib import Path

from bugfix_contracts.code_knowledge import DefectCodeMatch, MatchCandidate
from bugfix_platform.agents.cartographer.match import filter_existing_candidates


def _match(*paths: str, symbols: dict[str, str] | None = None) -> list[DefectCodeMatch]:
    symbols = symbols or {}
    return [
        DefectCodeMatch(
            defectId="D1",
            candidates=[
                MatchCandidate(
                    path=p,
                    why="sdk",
                    source="grep",
                    symbol=symbols.get(p),
                )
                for p in paths
            ],
            confidence="high",
        )
    ]


def test_filter_drops_comment_only_vacuum(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "empty.js").write_text("  // placeholder\n\n/* todo */\n", encoding="utf-8")
    (src / "real.js").write_text(
        "export function overlay() { return 1; }\n", encoding="utf-8"
    )
    filtered = filter_existing_candidates(
        tmp_path, _match("src/empty.js", "src/real.js")
    )
    assert [c.path for c in filtered[0].candidates] == ["src/real.js"]
    assert filtered[0].confidence in {"medium", "high"}


def test_filter_keeps_short_electron_preload(tmp_path: Path):
    """行数 < 20 但有真实声明的 preload 不得当死文件删。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "preload.js").write_text(
        "const { contextBridge } = require('electron');\n"
        "contextBridge.exposeInMainWorld('api', { ping: () => 1 });\n",
        encoding="utf-8",
    )
    filtered = filter_existing_candidates(tmp_path, _match("src/preload.js"))
    assert [c.path for c in filtered[0].candidates] == ["src/preload.js"]


def test_filter_drops_symbol_not_in_file(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "page.vue").write_text(
        "<script>export default { methods: { save() {} } }</script>\n",
        encoding="utf-8",
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _match("src/page.vue", symbols={"src/page.vue": "getTextOverlay"}),
    )
    assert filtered[0].candidates == []
    assert filtered[0].confidence == "low"


def test_filter_keeps_when_symbol_present(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "page.vue").write_text(
        "<script>export default { methods: { getTextOverlay() {} } }</script>\n",
        encoding="utf-8",
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _match("src/page.vue", symbols={"src/page.vue": "getTextOverlay"}),
    )
    assert [c.path for c in filtered[0].candidates] == ["src/page.vue"]


def test_filter_skips_symbol_gate_when_unset(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "page.vue").write_text(
        "<script>export default { methods: { save() {} } }</script>\n",
        encoding="utf-8",
    )
    filtered = filter_existing_candidates(tmp_path, _match("src/page.vue"))
    assert [c.path for c in filtered[0].candidates] == ["src/page.vue"]


def test_device_web_drops_empty_mixin_and_isapi(tmp_path: Path):
    overlay = tmp_path / "src" / "Config" / "view" / "snapOverlay"
    (overlay / "pc").mkdir(parents=True)
    (overlay / "pc" / "snapOverlay.vue").write_text(
        "<script>export default { methods: { dragOsd() {} } }</script>\n",
        encoding="utf-8",
    )
    (overlay / "mixin.js").write_text("export default {}\n", encoding="utf-8")
    (overlay / "isapi.js").write_text("/* ISAPI */\nexport default {}\n", encoding="utf-8")
    (overlay / "postHvtMixin.js").write_text(
        "export function validateDiversionZone() { return true; }\n",
        encoding="utf-8",
    )
    filtered = filter_existing_candidates(
        tmp_path,
        _match(
            "src/Config/view/snapOverlay/pc/snapOverlay.vue",
            "src/Config/view/snapOverlay/mixin.js",
            "src/Config/view/snapOverlay/isapi.js",
        ),
        profile="device_web",
        cap_confidence="medium",
    )
    kept = [c.path.replace("\\", "/") for c in filtered[0].candidates]
    assert kept == ["src/Config/view/snapOverlay/pc/snapOverlay.vue"]
    assert filtered[0].confidence == "medium"

    mixed = filter_existing_candidates(
        tmp_path,
        _match(
            "src/Config/view/snapOverlay/pc/snapOverlay.vue",
            "src/Config/view/snapOverlay/postHvtMixin.js",
        ),
        profile="device_web",
    )
    mixed_paths = [c.path.replace("\\", "/") for c in mixed[0].candidates]
    assert "src/Config/view/snapOverlay/postHvtMixin.js" in mixed_paths


def test_empty_mixin_kept_outside_device_web(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mixin.js").write_text("export default {}\n", encoding="utf-8")
    filtered = filter_existing_candidates(
        tmp_path, _match("src/mixin.js"), profile="electron_node"
    )
    assert [c.path for c in filtered[0].candidates] == ["src/mixin.js"]
