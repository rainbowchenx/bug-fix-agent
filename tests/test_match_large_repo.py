"""Large-repo cartography matching: rank src over tests, no tiny file hard-cap."""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_agent.agents.cartographer.detect import discover_repo_roots
from bugfix_agent.agents.cartographer.match import (
    MAX_CANDIDATES,
    MAX_FILES_DEFAULT,
    _tokens,
    _walk_files,
    match_tickets,
)
from bugfix_agent.contracts.defect_batch import BatchTicket
from bugfix_agent.contracts.code_knowledge import RepoRoot


def test_max_files_default_is_large():
    assert MAX_FILES_DEFAULT >= 10_000


def test_prefer_src_over_test_paths(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "src" / "node" / "routes").mkdir(parents=True)
    (work / "test" / "e2e").mkdir(parents=True)
    (work / "test" / "unit").mkdir(parents=True)
    (work / "src" / "node" / "routes" / "login.ts").write_text("export {}\n", encoding="utf-8")
    (work / "test" / "e2e" / "login.test.ts").write_text("export {}\n", encoding="utf-8")
    (work / "test" / "unit" / "login.test.ts").write_text("export {}\n", encoding="utf-8")
    (work / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")

    roots = discover_repo_roots(work)
    ticket = BatchTicket(
        defectId="1",
        title="【登录】login 路由密码正确仍 401",
        pool="strict",
        expectQuality="explicit",
        titleTag="登录",
        testModule="login",
        intent="unclear",
    )
    matched = match_tickets(work, roots, [ticket])
    paths = [c.path for c in matched[0].candidates]
    assert paths, "expected candidates"
    assert paths[0] == "src/node/routes/login.ts"
    assert len(paths) <= MAX_CANDIDATES


def test_weak_substring_loses_to_segment_match(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "packages" / "postcss" / "src").mkdir(parents=True)
    (work / "packages" / "node" / "src").mkdir(parents=True)
    (work / "packages" / "postcss" / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
    (work / "packages" / "node" / "src" / "optimize.ts").write_text("export {}\n", encoding="utf-8")
    (work / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")

    roots = discover_repo_roots(work)
    ticket = BatchTicket(
        defectId="1",
        title="optimize 开启后输出体积异常",
        pool="strict",
        expectQuality="explicit",
        testModule="optimize",
        titleTag="节点",
        intent="unclear",
    )
    matched = match_tickets(work, roots, [ticket])
    paths = [c.path for c in matched[0].candidates]
    assert paths[0].endswith("optimize.ts")


def test_walk_beyond_old_800_cap(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "pkg" / "deep").mkdir(parents=True)
    # Create >800 shallow noise files first in lexical order before pkg/deep target
    noise = work / "aaa_noise"
    noise.mkdir()
    for i in range(850):
        (noise / f"n{i:04d}.go").write_text("package n\n", encoding="utf-8")
    target = work / "pkg" / "deep" / "security.go"
    target.write_text("package deep\n", encoding="utf-8")

    files = _walk_files(work, max_files=MAX_FILES_DEFAULT)
    assert len(files) > 800
    assert any(f.endswith("pkg/deep/security.go") for f in files)

    roots = [RepoRoot(path=".", kind="app")]
    ticket = BatchTicket(
        defectId="1",
        title="security 策略未拦截",
        pool="strict",
        expectQuality="explicit",
        testModule="security",
        titleTag="策略",
        intent="unclear",
    )
    matched = match_tickets(work, roots, [ticket], max_files=MAX_FILES_DEFAULT)
    paths = [c.path for c in matched[0].candidates]
    assert any(p.endswith("security.go") for p in paths)


def test_generic_intent_config_not_tokenized():
    ticket = BatchTicket(
        defectId="1",
        title="gateway host 环境覆盖无效",
        pool="strict",
        expectQuality="explicit",
        testModule="gateway",
        titleTag="网关",
        intent="config",
    )
    toks = _tokens(ticket)
    assert "config" not in toks
    assert "gateway" in toks


def test_go_underscore_test_files_penalized(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "pkg" / "config").mkdir(parents=True)
    (work / "pkg" / "config" / "gateway.go").write_text("package config\n", encoding="utf-8")
    (work / "pkg" / "config" / "gateway_host_env_test.go").write_text(
        "package config\n", encoding="utf-8"
    )
    roots = [RepoRoot(path=".", kind="app")]
    ticket = BatchTicket(
        defectId="1",
        title="gateway host 环境覆盖无效",
        pool="strict",
        expectQuality="explicit",
        testModule="gateway",
        titleTag="网关",
        intent="unclear",
    )
    matched = match_tickets(work, roots, [ticket])
    assert matched[0].candidates[0].path.endswith("gateway.go")


def test_scoped_package_dir_beats_generic_plugin_name(tmp_path: Path):
    work = tmp_path / "repo"
    (work / "packages" / "@tailwindcss-vite" / "src").mkdir(parents=True)
    (work / "packages" / "tailwindcss" / "src").mkdir(parents=True)
    (work / "packages" / "@tailwindcss-vite" / "src" / "index.ts").write_text(
        "export {}\n", encoding="utf-8"
    )
    (work / "packages" / "tailwindcss" / "src" / "plugin.ts").write_text(
        "export {}\n", encoding="utf-8"
    )
    (work / "package.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    roots = discover_repo_roots(work)
    ticket = BatchTicket(
        defectId="1",
        title="@tailwindcss-vite plugin 未监听文件变更",
        pool="strict",
        expectQuality="explicit",
        testModule="vite",
        titleTag="vite",
        intent="unclear",
    )
    matched = match_tickets(work, roots, [ticket])
    assert "tailwindcss-vite" in matched[0].candidates[0].path.replace("@", "")
