"""仓型探测的两个事实：TS 要证据才算；CLAUDE.md 只取判据不抄正文。"""

from __future__ import annotations

from pathlib import Path

from bugfix_platform.agents.cartographer.detect import (
    _has_typescript,
    detect_cartography_profile,
    discover_repo_roots,
    read_conventions,
)
from tests.helpers import ensure_git_repo


def _pkg(repo: Path, deps: dict | None = None, *, auto: dict | None = None) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    import json

    payload = {"name": repo.name, "version": "1.0.0"}
    if deps:
        payload["dependencies"] = deps
    if auto:
        payload["autoDependencies"] = auto
    (repo / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    ensure_git_repo(repo)


def test_typescript_needs_evidence_not_just_a_manifest(tmp_path: Path):
    """有 package.json 不等于有 TS —— transport / peitao 的 .ts 文件数是 0。"""
    repo = tmp_path / "web"
    _pkg(repo, {"vue": "^2.7.0"})
    (repo / "src").mkdir()
    (repo / "src" / "app.js").write_text("export default {}\n", encoding="utf-8")

    _profile, _hints, tech = detect_cartography_profile(tmp_path, discover_repo_roots(tmp_path))
    assert tech["languages"] == ["javascript"], tech["languages"]


def test_typescript_from_source_files(tmp_path: Path):
    repo = tmp_path / "app"
    _pkg(repo)
    (repo / "src").mkdir()
    (repo / "src" / "main.ts").write_text("export const a = 1\n", encoding="utf-8")

    _p, _h, tech = detect_cartography_profile(tmp_path, discover_repo_roots(tmp_path))
    assert tech["languages"] == ["javascript", "typescript"], tech["languages"]


def test_typescript_from_tsconfig(tmp_path: Path):
    repo = tmp_path / "lib"
    _pkg(repo)
    (repo / "tsconfig.json").write_text("{}", encoding="utf-8")

    _p, _h, tech = detect_cartography_profile(tmp_path, discover_repo_roots(tmp_path))
    assert "typescript" in tech["languages"]


def test_typescript_ignores_node_modules(tmp_path: Path):
    """依赖目录里的 .ts 不算本仓用 TypeScript。"""
    repo = tmp_path / "web"
    _pkg(repo)
    dep = repo / "node_modules" / "some-lib"
    dep.mkdir(parents=True)
    (dep / "index.d.ts").write_text("export {};\n", encoding="utf-8")

    assert _has_typescript(repo) is False


def test_typescript_can_use_an_existing_file_list(tmp_path: Path):
    """给了文件表就不走盘（慢盘上这是几秒的差别）。"""
    repo = tmp_path / "web"
    _pkg(repo)
    assert _has_typescript(repo, ["src/a.js", "src/b.vue"]) is False
    assert _has_typescript(repo, ["src/a.ts"]) is True


def test_claude_md_signals_kept_but_text_not_copied(tmp_path: Path):
    """CLAUDE.md 仍要能判 codeGraph / frameworkId，但正文截取不进产物。"""
    repo = tmp_path / "app"
    _pkg(repo)
    (repo / "CLAUDE.md").write_text(
        "# 项目说明\n\n搜索请用 CodeGraph，流程走 superpowers。\n第二段正文不该出现在产物里。\n",
        encoding="utf-8",
    )

    conv = read_conventions(tmp_path, discover_repo_roots(tmp_path))
    assert conv["codeGraph"] is True
    assert conv["frameworkId"] == "superpowers"
    assert conv["fromClaudeMd"] == []
    assert any(e.path.endswith("CLAUDE.md") for e in conv["entries"])
    joined = " ".join(conv["fromClaudeMd"])
    assert "第二段正文" not in joined


def test_codegraph_db_sets_capability_without_claude_md(tmp_path: Path):
    repo = tmp_path / "app"
    _pkg(repo)
    db = repo / ".codegraph"
    db.mkdir()
    (db / "codegraph.db").write_bytes(b"sqlite-fake" * 8)
    conv = read_conventions(tmp_path, discover_repo_roots(tmp_path))
    assert conv["codeGraph"] is True


def test_profile_is_never_detected_only_echoed(tmp_path: Path):
    """detect 不判型：第一个返回值恒为 unknown，仓型由调用方给。"""
    repo = tmp_path / "mf"
    _pkg(repo, {"single-spa": "^5.0.0", "vue": "^2.7.0"})
    profile, hints, _tech = detect_cartography_profile(tmp_path, discover_repo_roots(tmp_path))
    assert profile == "unknown"
    assert any(h.endswith(":single-spa") for h in hints), hints


def test_trellis_spec_dirs_indexed_as_doc_ref_without_copying_body(tmp_path: Path):
    """磁盘有 .trellis/spec 就建路径索引；markdown 正文不进产物。"""
    _pkg(tmp_path)
    for app in ("HCBVideo", "HCBSystem"):
        d = tmp_path / ".trellis" / "spec" / "src" / app / "frontend"
        d.mkdir(parents=True)
        (d / "README.md").write_text("# 规范正文不该出现在产物里\n", encoding="utf-8")
    (tmp_path / ".trellis" / "spec" / "src" / "HCBVideo" / "backend").mkdir(parents=True)

    conv = read_conventions(tmp_path, discover_repo_roots(tmp_path))
    assert conv["frameworkId"] == "trellis"
    refs = [e.path.replace("\\", "/") for e in conv["entries"] if e.kind == "doc_ref"]
    assert any("HCBVideo/frontend" in p for p in refs), refs
    assert any("HCBSystem/frontend" in p for p in refs), refs
    assert any("HCBVideo/backend" in p for p in refs), refs
    blob = " ".join(e.path for e in conv["entries"])
    assert "规范正文" not in blob


def test_trellis_does_not_override_superpowers_or_drop_claude_md(tmp_path: Path):
    """CLAUDE.md 已判 superpowers 时不改 frameworkId；原 guide 条目保留。"""
    _pkg(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("搜索走 CodeGraph，流程走 superpowers。\n", encoding="utf-8")
    d = tmp_path / ".trellis" / "spec" / "src" / "HCBPortal" / "frontend"
    d.mkdir(parents=True)
    conv = read_conventions(tmp_path, discover_repo_roots(tmp_path))
    assert conv["frameworkId"] == "superpowers"
    assert conv["codeGraph"] is True
    kinds = {e.kind for e in conv["entries"]}
    assert "guide" in kinds
    assert "doc_ref" in kinds
    assert any(e.path.replace("\\", "/").endswith("CLAUDE.md") for e in conv["entries"])
    assert any(e.kind == "doc_ref" and "HCBPortal" in e.path for e in conv["entries"])


def test_no_trellis_dir_does_not_invent_doc_refs(tmp_path: Path):
    _pkg(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# hi\n", encoding="utf-8")
    conv = read_conventions(tmp_path, discover_repo_roots(tmp_path))
    assert conv["frameworkId"] == "unknown"
    assert all(e.kind != "doc_ref" for e in conv["entries"])
