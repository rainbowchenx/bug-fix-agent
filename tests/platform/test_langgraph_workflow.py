import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END

from bugfix_platform.workflow import create_three_agent_graph, run_three_agent_workflow
from bugfix_platform.workflow.graph import default_three_agent_graph
from tests.helpers import defect_batch_from_hc1


def _mini_work(tmp_path: Path) -> Path:
    work = tmp_path / "mini"
    (work / "src").mkdir(parents=True)
    (work / "package.json").write_text(
        json.dumps({"name": "mini-hc", "version": "0.0.1", "dependencies": {"electron": "30.0.0"}}),
        encoding="utf-8",
    )
    (work / "CLAUDE.md").write_text("# Mini\nUse CodeGraph for search.\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    return work


def test_default_graph_compiles():
    g = default_three_agent_graph
    nodes = set(g.get_graph().nodes)
    assert "agent1" not in nodes
    assert "agent2" in nodes
    assert "agent3" in nodes
    assert "validate_batch" in nodes
    assert "validate_knowledge" in nodes
    assert "validate_report" in nodes


def test_langgraph_e2e_invoke(tmp_path: Path):
    work = _mini_work(tmp_path)
    batch = defect_batch_from_hc1()
    graph = create_three_agent_graph()
    final = graph.invoke(
        {
            "work_dir": str(work),
            "product_line": "hc",
            "posture": "alpha",
            "defect_batch": batch.model_dump(),
            "open_mr": False,
            "skip_agent2": False,
            "skip_agent3": False,
            "cartography_profile": "electron_node",
            "ok": True,
            "stage": "agent2",
            "error": None,
        }
    )
    assert final["ok"] is True
    assert final["stage"] == "done"
    assert final["defect_batch"]["funnel"]["total"] == 50
    assert final["code_knowledge"]["cartographyProfile"] == "electron_node"
    assert final["analysis_report"]["summary"]["total"] >= 1


def test_langgraph_skip_agent2_and_3(tmp_path: Path):
    work = _mini_work(tmp_path)
    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        skip_agent2=True,
        skip_agent3=True,
    )
    assert result.ok is True
    assert result.stage == "done"
    assert result.artifacts.defect_batch is not None
    assert result.artifacts.code_knowledge is None
    assert result.artifacts.analysis_report is None


def test_langgraph_hard_stop_invalid_agent2():
    def bad_agent2(**_kwargs):
        return {"broken": True}

    result = run_three_agent_workflow(
        work_dir="/tmp/x",
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        agent2=bad_agent2,
    )
    assert result.ok is False
    assert result.stage == "agent2"
    assert "code-knowledge" in (result.error or "")


def test_routing_helpers_end_constant():
    # Guard: conditional / Command edges use the same END sentinel LangGraph expects.
    assert END == "__end__"


def test_langgraph_checkpointer_thread_and_updates(tmp_path: Path):
    work = _mini_work(tmp_path)
    stages: list[str] = []

    def on_update(state: dict) -> None:
        stage = state.get("stage")
        if stage and (not stages or stages[-1] != stage):
            stages.append(stage)

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
        cartography_mode="heuristic",
        thread_id="test-thread-1",
        checkpointer=InMemorySaver(),
        on_update=on_update,
    )
    assert result.ok is True
    assert result.stage == "done"
    assert "agent1" not in stages
    assert "agent2" in stages
    assert "done" in stages


def test_langgraph_progressive_artifact_dir(tmp_path: Path):
    work = _mini_work(tmp_path)
    out = tmp_path / "artifacts"
    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
        cartography_mode="heuristic",
        artifact_dir=out,
    )
    assert result.ok is True
    assert (out / "defect-batch.json").is_file()
    assert (out / "code-knowledge.json").is_file()
    assert (out / "analysis-report.json").is_file()
    batch = json.loads((out / "defect-batch.json").read_text(encoding="utf-8"))
    assert batch["funnel"]["total"] == 50
