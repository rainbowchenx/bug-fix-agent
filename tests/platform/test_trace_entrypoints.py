"""Trace presentation through the CLI and the packaged Nexas graph."""

import json
import runpy
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from bugfix_contracts import env
from bugfix_platform import cli
from tests.helpers import ensure_git_repo
from tests.platform.test_agent3_sdk_report import _batch, _mini_repo


@pytest.mark.parametrize("entrypoint, mode", [
    ("cli", "summary"), ("cli", "detailed"), ("nexas", "detailed"),
])
def test_trace_presentation_through_workflow(tmp_path, monkeypatch, capsys, entrypoint, mode):
    import claude_agent_sdk

    monkeypatch.setattr(env, "load_env_file", lambda: None)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    work = ensure_git_repo(_mini_repo(tmp_path))
    batch = tmp_path / "batch.json"
    batch.write_text(_batch(work).model_dump_json(), encoding="utf-8")
    output = tmp_path / "out"
    payload = {
        "outcome": "plan_only",
        "rootCause": {"summary": "Race in preview", "claims": [], "questions": []},
        "proposedFix": {"summary": "Serialize initialization", "steps": ["Guard re-entry"]},
        "localization": {"candidates": [{"path": "src/preview-player.ts", "source": "read"}]},
    }

    async def query(*, prompt, options):
        assert options.include_partial_messages == (mode == "detailed")
        yield AssistantMessage(content=[TextBlock(text="Inspecting preview")], model="m")
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1,
            is_error=False, num_turns=1, session_id="s1", structured_output=payload,
        )

    monkeypatch.setattr(claude_agent_sdk, "query", query)
    if entrypoint == "cli":
        assert cli.main([
            "run", "--work-dir", str(work), "--defect-batch", str(batch),
            "--out-dir", str(output), "--cartography-profile", "electron_node",
            "--cartography-mode", "heuristic", "--analyze-mode", "sdk", "--trace-mode", mode,
        ]) == 0
        live = capsys.readouterr()
        assert json.loads(live.out)["ok"] is True
        if mode == "detailed":
            assert "Inspecting preview" in live.err
            assert "Serialize initialization" in live.err
        else:
            assert "[agent3] turn 1" in live.err
            assert "Inspecting preview" not in live.err
    else:
        params = tmp_path / "params.json"
        params.write_text(json.dumps({
            "work_dir": str(work), "defect_batch": str(batch), "artifact_dir": str(output),
            "cartography_profile": "electron_node",
            "cartography_mode": "heuristic", "analyze_mode": "sdk", "trace_mode": mode,
        }), encoding="utf-8")
        wrapper = Path(__file__).resolve().parents[2] / "packaging" / "platform" / "graph.py"
        graph = runpy.run_path(str(wrapper))["graph"]
        result = graph.invoke({"input": str(params)})
        assert result["ok"] is True, result["result"]
        assert "Inspecting preview" in capsys.readouterr().out
        assert "Serialize initialization" in result["result"]
        assert str(output / "logs") in result["result"]

    assert "Serialize initialization" in (output / "analysis-report.md").read_text(encoding="utf-8")
    records = [
        json.loads(line) for line in (output / "logs" / "agent3-D1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if mode == "detailed":
        assert records[-1]["structuredOutput"] == payload
