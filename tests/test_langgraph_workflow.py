import json
from pathlib import Path

from langgraph.graph import END

from bugfix_agent.workflow import create_three_agent_graph, run_three_agent_workflow
from bugfix_agent.workflow.graph import default_three_agent_graph

ROOT = Path(__file__).resolve().parents[1]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


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
    assert "agent1" in nodes
    assert "agent2" in nodes
    assert "agent3" in nodes


def test_langgraph_e2e_invoke(tmp_path: Path):
    work = _mini_work(tmp_path)
    graph = create_three_agent_graph()
    final = graph.invoke(
        {
            "work_dir": str(work),
            "product_line": "hc",
            "posture": "alpha",
            "source": str(HC1),
            "open_mr": False,
            "skip_agent2": False,
            "skip_agent3": False,
            "ok": True,
            "stage": "agent1",
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
        source=HC1,
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
        source=HC1,
        agent2=bad_agent2,
    )
    assert result.ok is False
    assert result.stage == "agent2"
    assert "code-knowledge" in (result.error or "")


def test_routing_helpers_end_constant():
    # Guard: conditional edges use the same END sentinel LangGraph expects.
    assert END == "__end__"
