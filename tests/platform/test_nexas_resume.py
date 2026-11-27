import json
import runpy
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage

from bugfix_contracts import env
from tests.helpers import ensure_git_repo
from tests.platform.test_agent3_sdk_report import _batch, _mini_repo


@pytest.mark.parametrize("feedback_format", ["json", "md"])
def test_nexas_resumes_ticket_and_injects_separate_repair_skill(tmp_path, monkeypatch, feedback_format):
    import claude_agent_sdk

    monkeypatch.setattr(env, "load_env_file", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    work = ensure_git_repo(_mini_repo(tmp_path))
    source = work / "src" / "preview-player.ts"
    original = "function preview() { return; }\n"
    source.write_text(original, encoding="utf-8")
    project_skill = work / ".claude" / "skills" / "preview" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("---\nname: preview\nprofiles: bugfix\n---\nProject preview convention.", encoding="utf-8")
    repair_skill = tmp_path / "user-skill" / "SKILL.md"
    repair_skill.parent.mkdir()
    repair_skill.write_text("---\nname: preview\nprofiles: unrelated\n---\nUser requires a retry guard.", encoding="utf-8")
    (work / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"docs": {"type": "http", "url": "http://localhost:1/mcp"}},
    }), encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(_batch(work).model_dump_json(), encoding="utf-8")
    output = tmp_path / "round-1"
    phases = []
    resumed = False

    async def query(*, prompt, options):
        system = options.system_prompt
        if "Agent-3 fix editor" in system:
            phases.append("fix")
            assert resumed
            isolated = Path(options.cwd)
            assert isolated != work
            (isolated / source.relative_to(work)).write_text(
                "function preview() { guard(); return; }\n", encoding="utf-8",
            )
            payload = {
                "commitMessage": "fix: restore preview retry (D1)",
                "semanticReviewStatus": "passed", "semanticReviewExecuted": True,
                "semanticReview": "guard restores preview retry without changing the success path",
            }
        else:
            phases.append("analyze")
            if resumed:
                assert "Only fails after switching devices" in prompt
                assert "Only investigate evidence affected by the new feedback" in prompt
                assert "preview loses state on device switch" in prompt
            payload = {
                "outcome": "plan_only",
                "rootCause": {"summary": "preview loses state on device switch", "questions": [], "claims": []},
                "proposedFix": {"summary": "Guard preview retry", "targetFiles": ["src/preview-player.ts"]},
                "localization": {"candidates": [{
                    "path": "src/preview-player.ts", "symbol": "preview", "source": "grep", "snippet": original.strip(),
                }]},
            }
        if resumed:
            assert "Project preview convention." in system
            assert "## Required user repair Skill — preview" in system
            assert "User requires a retry guard." in system
            assert system.index("Project preview convention.") < system.index("User requires a retry guard.")
            assert options.strict_mcp_config is False
            assert {"docs"} <= set(options.mcp_servers)
            assert options.setting_sources == ["user", "project", "local"]
        else:
            assert options.strict_mcp_config is True
            assert "User requires a retry guard." not in system
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
            num_turns=1, session_id="session", result=json.dumps(payload), structured_output=payload,
            usage={"input_tokens": 12, "output_tokens": 4},
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    graph_path = Path(__file__).resolve().parents[2] / "packaging" / "platform" / "graph.py"
    graph = runpy.run_path(str(graph_path))["graph"]

    def invoke(params):
        config = tmp_path / "params.json"
        config.write_text(json.dumps(params), encoding="utf-8")
        return graph.invoke({"input": str(config)})

    first = invoke({
        "work_dir": str(work), "defect_batch": "batch.json", "artifact_dir": "round-1",
        "cartography_profile": "electron_node", "cartography_mode": "heuristic", "analyze_mode": "sdk",
        "apply_fix": False,
    })
    assert first["ok"], first["result"]
    latest = output / "defects" / "D1" / "latest.json"
    parent = json.loads(latest.read_text(encoding="utf-8"))["attemptId"]
    feedback = tmp_path / f"feedback.{feedback_format}"
    if feedback_format == "json":
        feedback.write_text(json.dumps({
            "defectId": "D1", "feedbackId": "f1", "kind": "supplement_fact",
            "observed": "Only fails after switching devices", "attemptId": parent,
        }), encoding="utf-8")
    else:
        form = latest.with_name("feedback-form.md").read_text(encoding="utf-8")
        feedback.write_text(form.replace(
            "<!-- ANSWER:observed -->\n",
            "<!-- ANSWER:observed -->\nOnly fails after switching devices\n",
        ), encoding="utf-8")
    params = {
        "action": "resume", "artifact_dir": "round-1", "defect_id": "D1",
        "feedback_file": feedback.name, "repair_skill": "user-skill",
        "project_integrations": True, "apply_fix": True, "analyze_mode": "sdk",
    }
    invalid = invoke({**params, "repair_skill": "missing/SKILL.md"})
    assert not invalid["ok"] and "repair_skill" in invalid["result"]
    assert not latest.with_name("feedback-latest.json").exists()

    resumed = True
    second = invoke(params)
    assert second["ok"], second["result"]
    assert phases == ["analyze", "analyze", "fix"]
    assert "续跑票号：D1" in second["result"]
    assert source.read_text(encoding="utf-8") == original
    report = json.loads((output / "analysis-report.json").read_text(encoding="utf-8"))
    assert report["tickets"][0]["outcome"] == "patch_ready"
    usage = report["tickets"][0]["analysisUsage"]
    assert (usage["turns"], usage["inputTokens"], usage["readCalls"]) == (1, 12, 0)
    assert "analysisUsage: turns=1" in (output / "analysis-report.md").read_text(encoding="utf-8")
    assert any(item.get("source") == "user_repair" for item in report["skillDiscovery"])
    attempt_id = json.loads(latest.read_text(encoding="utf-8"))["attemptId"]
    attempt = json.loads((latest.parent / "attempts" / attempt_id / "attempt.json").read_text(encoding="utf-8"))
    assert attempt["parentAttemptId"] == parent


@pytest.mark.parametrize("change", ["none", "unrelated", "relevant", "new_session"])
def test_nexas_resume_recovers_tool_history_from_same_session(tmp_path, monkeypatch, change):
    from types import SimpleNamespace

    import claude_agent_sdk
    from bugfix_platform.agents.analyst.attempt_store import load_attempt

    monkeypatch.setattr(env, "load_env_file", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("BUGFIX_CODEGRAPH", "0")
    work = ensure_git_repo(_mini_repo(tmp_path))
    batch = tmp_path / "batch.json"
    batch.write_text(_batch(work).model_dump_json(), encoding="utf-8")
    output = tmp_path / "round-1"
    source = work / "src" / "preview-player.ts"
    actions = [
        ("Read", {"file_path": str(source), "offset": 1, "limit": 20}, change in {"none", "unrelated"}),
        ("Grep", {"path": str(source.parent), "pattern": "preview"}, change in {"none", "unrelated"}),
    ]

    async def query(*, prompt, options):
        session = "session-1"
        resumed = options.resume == session
        if resumed and change == "new_session":
            session = "session-2"
        yield SimpleNamespace(subtype="init", data={"session_id": session, "mcp_servers": []})
        hook = options.hooks["PreToolUse"][-1].hooks[0]
        for tool, params, should_dedupe in actions:
            tool_id = tool.lower()
            decision = await hook({"tool_name": tool, "tool_input": params}, tool_id, None)
            blocked = decision.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            assert blocked == (resumed and should_dedupe)
            if not blocked:
                yield SimpleNamespace(content=[SimpleNamespace(tool_use_id=tool_id, is_error=False, content="source result")])
        data = {
            "outcome": "needs_ticket_info",
            "rootCause": {"summary": "Missing detail", "claims": [], "questions": []},
            "localization": {"candidates": []},
            "blockers": {"kind": "needs_ticket_info", "detail": "Which device?"},
        }
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                            num_turns=1, session_id=session, structured_output=data)

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    graph = runpy.run_path(str(Path(__file__).resolve().parents[2] / "packaging/platform/graph.py"))["graph"]

    def invoke(params):
        result = graph.invoke({"input": json.dumps(params)})
        assert result["ok"], result["result"]
        return json.loads((output / "analysis-report.json").read_text(encoding="utf-8"))["tickets"][0]

    first = invoke({"work_dir": str(work), "defect_batch": str(batch), "artifact_dir": str(output),
                    "cartography_mode": "heuristic", "analyze_mode": "sdk"})
    attempt = load_attempt(output / "defects" / "D1" / "attempts" / first["attemptId"] / "attempt.json")
    assert attempt.analysisToolHistory.reads[0].path == "src/preview-player.ts"
    assert attempt.analysisToolHistory.queries[0].scope == "src"
    if change == "relevant":
        source.write_text("export const preview = 2;", encoding="utf-8")
    elif change == "unrelated":
        (work / "other.ts").write_text("export const other = 1;", encoding="utf-8")
    second = invoke({"action": "resume", "artifact_dir": str(output), "defect_id": "D1", "analyze_mode": "sdk"})
    stats = second["analysisUsage"]
    assert (stats["readRequests"], stats["grepGlobRequests"]) == (1, 1)
    assert (stats["readBlocked"], stats["grepGlobBlocked"]) == tuple(int(blocked) for _, _, blocked in actions)
    assert (stats["readCalls"], stats["grepGlobCalls"]) == tuple(int(not blocked) for _, _, blocked in actions)
