import json
import sys
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from bugfix_contracts.code_knowledge import RepoRoot
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.sdk.analyze import run_claude_analyze
from bugfix_platform.sdk.codegraph import CodeGraphStatus
from bugfix_platform.sdk.fix import FixRequest, run_claude_fix
from bugfix_platform.sdk.project_mcp import load_project_mcp
from bugfix_platform.workflow.run import run_three_agent_workflow
from tests.platform.test_repair_entry import _batch, _knowledge


TOOL = "mcp__business_docs__search"
CODEGRAPH = "mcp__codegraph__codegraph_explore"


def write_mcp(root: Path, servers: dict) -> None:
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_full_integrations_load_all_repo_servers_and_installed_plugins(tmp_path, monkeypatch):
    work = tmp_path / "work"
    nested = work / "nested"
    nested.mkdir(parents=True)
    write_mcp(work, {"docs": {"type": "http", "url": "https://example.invalid/mcp"}})
    write_mcp(nested, {"docs": {"command": "node", "args": ["server.js"]}, "extra": {"command": "extra"}})
    config = tmp_path / "claude"
    registry = config / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    user_plugin, project_plugin, other_plugin = [tmp_path / name for name in ("user", "project", "other")]
    for plugin in (user_plugin, project_plugin, other_plugin):
        plugin.mkdir()
    registry.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "preview@company": [
                {"scope": "user", "installPath": str(user_plugin)},
                {"scope": "project", "projectPath": str(nested), "installPath": str(project_plugin)},
            ],
            "other@company": [
                {"scope": "local", "projectPath": str(tmp_path), "installPath": str(other_plugin)},
            ],
        },
    }), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    project = load_project_mcp(work, [RepoRoot(path="nested")], full_access=True)
    isolated = tmp_path / "isolated"
    options = project.sdk_options(str(isolated))
    assert options["strict_mcp_config"] is False
    assert options["setting_sources"] == ["user", "project", "local"]
    assert options["plugins"] == [{"type": "local", "path": str(project_plugin)}]
    assert options["add_dirs"] == [str(isolated / "nested")]
    assert {"docs", "extra"} < set(options["mcp_servers"])
    alias, = set(options["mcp_servers"]) - {"docs", "extra"}
    assert alias.startswith("docs-")
    assert options["mcp_servers"][alias]["args"][-3:] == [str(isolated / "nested"), "node", "server.js"]
    assert f"mcp__{alias}__*" in project.allowed_tools()
    approve = options["can_use_tool"]
    assert anyio.run(approve, "mcp__a-native-plugin__new-tool", {}, None).behavior == "allow"
    assert anyio.run(approve, "Skill", {}, None).behavior == "allow"
    assert anyio.run(approve, "Bash", {}, None).behavior == "deny"


def test_agent2_sdk_receives_full_integrations(tmp_path, monkeypatch):
    from claude_agent_sdk import ResultMessage

    import claude_agent_sdk
    from bugfix_platform.sdk.cartography import query_cartography
    from tests.platform.test_investigation_batches import request

    work = tmp_path / "repo"
    work.mkdir()
    write_mcp(work, {"docs": {"type": "http", "url": "https://example.invalid/mcp"}})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    project = load_project_mcp(work, [], full_access=True)
    seen = []

    async def query(*, prompt, options):
        seen.append(options)
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="s",
            structured_output={"defectCodeMatches": [{"defectId": "0"}]},
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    req = request(work, 1)
    req.project_mcp = project
    result = query_cartography(req)
    assert result.parsed is not None
    assert seen[0].strict_mcp_config is False
    assert "mcp__docs__*" in seen[0].allowed_tools and "Bash" in seen[0].disallowed_tools
    assert seen[0].permission_mode == "default"


@pytest.mark.parametrize("enable_graph", [False, True])
@pytest.mark.parametrize("hook_on_failure", [False, True])
def test_agent3_keeps_approved_business_mcp_and_skills(tmp_path, monkeypatch, enable_graph, hook_on_failure):
    from bugfix_platform.agents.analyst import run as analyst_run
    from bugfix_platform.sdk import claude_cli

    monkeypatch.setattr(claude_cli, "hook_on_failure_supported", lambda: hook_on_failure)
    work = tmp_path / "project"
    skill = work / ".claude" / "skills" / "business-rule" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: business-rule\ndescription: use approved tools\nprofiles: [analyze]\n---\nBusiness rule.\n",
        encoding="utf-8",
    )
    write_mcp(work, {
        "business_docs": {"type": "http", "url": "http://localhost:12345/mcp"},
        "other": {"command": "unused"},
        "codegraph": {"command": "repository-version"},
    })
    status = CodeGraphStatus(ready=enable_graph, bin="bundled-codegraph")
    monkeypatch.setattr(analyst_run, "ensure_codegraph", lambda *_: status)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    seen = []

    async def query(*, prompt, options):
        seen.append(options)
        yield result

    result = SimpleNamespace(
        is_error=False, result="", structured_output={
            "outcome": "plan_only",
            "rootCause": {"summary": "inspected", "claims": [], "questions": []},
            "proposedFix": {"summary": "review", "steps": [], "targetFiles": []},
            "localization": {"candidates": []},
        },
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace(
        ClaudeAgentOptions=dict, HookMatcher=SimpleNamespace, ResultMessage=SimpleNamespace, query=query,
    ))
    report = run_analyst(
        work_dir=work, defect_batch=_batch(), code_knowledge=_knowledge(work),
        analyze_fn=run_claude_analyze, agent3_mcp_tools=[TOOL], apply_fix=False,
    )
    assert report.tickets[0].analysisStatus == "completed"
    assert "business-rule" in report.boundSkills
    assert len(seen) == 1
    options = seen[0]
    assert options["strict_mcp_config"] is True
    assert "business-rule" in options["system_prompt"]
    assert set(options["mcp_servers"]) == ({"business_docs", "codegraph"} if enable_graph else {"business_docs"})
    assert TOOL in options["allowed_tools"]
    assert (CODEGRAPH in options["allowed_tools"]) == enable_graph
    hook = options["hooks"]["PreToolUse"][0]
    assert getattr(hook, "on_failure", None) == ("block" if hook_on_failure else None)
    callback = hook.hooks[0]
    assert anyio.run(callback, {"tool_name": TOOL}, None, None) == {}
    denied = anyio.run(callback, {"tool_name": "mcp__business_docs__write"}, None, None)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_project_stdio_uses_own_repo_and_fix_copy(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace(HookMatcher=SimpleNamespace))
    source = tmp_path / "source"
    child = source / "business"
    child.mkdir(parents=True)
    write_mcp(child, {"business_docs": {"command": "node", "args": ["./mcp.js"]}})
    project = load_project_mcp(source, [RepoRoot(path="business")], [TOOL])
    fix = tmp_path / "fix"
    (fix / "business").mkdir(parents=True)
    for root in (source, fix):
        args = project.sdk_options(str(root))["mcp_servers"]["business_docs"]["args"]
        assert args[-3:] == [str(root / "business"), "node", "./mcp.js"]


@pytest.mark.parametrize("bad_tool", ["business_docs", "mcp__business_docs__*", CODEGRAPH])
def test_mcp_approval_requires_an_exact_business_tool(tmp_path, bad_tool):
    with pytest.raises(ValueError, match="must use"):
        load_project_mcp(tmp_path, [], [bad_tool])


def test_project_mcp_ignores_files_without_approval_and_rejects_ambiguous_sources(tmp_path):
    root = tmp_path / "repo"
    sub = root / "sub"
    sub.mkdir(parents=True)
    (root / ".mcp.json").write_text("not JSON", encoding="utf-8")
    assert not load_project_mcp(root, []).servers
    write_mcp(root, {"business_docs": {"command": "one"}})
    write_mcp(sub, {"business_docs": {"command": "two"}})
    with pytest.raises(ValueError, match="more than one repository"):
        load_project_mcp(root, [RepoRoot(path="sub")], [TOOL])
    with pytest.raises(ValueError, match="not found"):
        load_project_mcp(root, [], ["mcp__unknown__search"])


def test_fix_uses_the_same_explicit_business_tool_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    write_mcp(tmp_path, {"business_docs": {"type": "http", "url": "http://localhost:12345/mcp"}})
    project = load_project_mcp(tmp_path, [], [TOOL])

    async def query(*, prompt, options):
        assert options["strict_mcp_config"]
        assert list(options["mcp_servers"]) == ["business_docs"]
        assert TOOL in options["allowed_tools"]
        yield SimpleNamespace(is_error=False, result="{}")

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", SimpleNamespace(
        ClaudeAgentOptions=dict, HookMatcher=SimpleNamespace, ResultMessage=SimpleNamespace, query=query,
    ))
    result = run_claude_fix(FixRequest(
        work_dir=str(tmp_path), worktree_path=str(tmp_path), ticket=_batch().tickets[0],
        analysis={}, project_mcp=project,
    ))
    assert result.source == "sdk"


def test_workflow_forwards_approval_to_agent3_only(tmp_path, monkeypatch):
    monkeypatch.setenv("BUGFIX_CODEGRAPH", "0")
    work = tmp_path / "repo"
    work.mkdir()
    write_mcp(work, {"business_docs": {"type": "http", "url": "http://localhost:12345/mcp"}})
    approvals = []

    def cartographer(**kwargs):
        assert "agent3_mcp_tools" not in kwargs
        return _knowledge(work)

    def analyst(**kwargs):
        approvals.extend(kwargs["agent3_mcp_tools"])
        return run_analyst(**kwargs, analyze_mode="heuristic")

    result = run_three_agent_workflow(
        work_dir=work, product_line="hc", defect_batch=_batch(),
        agent2=cartographer, agent3=analyst, agent3_mcp_tools=[TOOL], artifact_dir=tmp_path / "artifacts",
    )
    assert result.ok, result.error
    assert approvals == [TOOL]


def test_resume_cli_forwards_new_run_approval(monkeypatch):
    from bugfix_platform import cli

    captured = []

    def resume(*args, agent3_mcp_tools, **kwargs):
        captured.extend(agent3_mcp_tools)
        return 0

    monkeypatch.setattr(cli, "_cmd_resume", resume)
    assert cli.main([
        "resume", "--root", "unused", "--defect-id", "D1", "--execute",
        "--agent3-mcp-tool", TOOL,
    ]) == 0
    assert captured == [TOOL]
