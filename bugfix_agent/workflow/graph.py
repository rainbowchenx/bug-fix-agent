from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from langgraph.graph import END, START, StateGraph

from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.contracts import CodeKnowledge
from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.workflow.gates import (
    ArtifactValidationError,
    require_analysis_report,
    require_code_knowledge,
    require_defect_batch,
)
from bugfix_agent.workflow.state import ThreeAgentState

CartographerFn = Callable[..., CodeKnowledge]
AnalystFn = Callable[..., Any]


def create_three_agent_graph(
    *,
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
):
    """Build the parent LangGraph: validate → 1 → validate → 2 → validate → 3.

    Agent callables are closed over so tests can inject stubs without putting
    non-serializable callables into checkpoint state.
    """
    cartographer = agent2 or run_cartographer
    analyst = agent3 or run_analyst

    def agent1_node(state: ThreeAgentState) -> dict[str, Any]:
        try:
            existing = state.get("defect_batch")
            if existing is not None:
                batch = require_defect_batch(existing)
            else:
                source = state.get("source")
                if source is None:
                    return {
                        "ok": False,
                        "stage": "agent1",
                        "error": "source or defect_batch is required",
                    }
                prepared = run_defect_batch_prepare(
                    product_line=state["product_line"],
                    mode="preloaded",
                    source=source,
                    posture=state.get("posture") or "beta",
                )
                batch = require_defect_batch(prepared.model_dump())

            both_skip = bool(state.get("skip_agent2")) and bool(state.get("skip_agent3"))
            return {
                "defect_batch": batch.model_dump(),
                "ok": True,
                "stage": "done" if both_skip else "agent1",
                "error": None,
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "stage": "agent1", "error": _err_message(err)}

    def agent2_node(state: ThreeAgentState) -> dict[str, Any]:
        try:
            batch = require_defect_batch(state["defect_batch"])
            call_kwargs: dict[str, Any] = {
                "work_dir": state["work_dir"],
                "defect_batch": batch,
            }
            if state.get("cartography_mode"):
                call_kwargs["cartography_mode"] = state["cartography_mode"]
            try:
                knowledge = cartographer(**call_kwargs)
            except TypeError:
                call_kwargs.pop("cartography_mode", None)
                knowledge = cartographer(**call_kwargs)
            validated = require_code_knowledge(
                knowledge.model_dump() if hasattr(knowledge, "model_dump") else knowledge
            )
            skip3 = bool(state.get("skip_agent3"))
            return {
                "code_knowledge": validated.model_dump(),
                "ok": True,
                "stage": "done" if skip3 else "agent2",
                "error": None,
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "stage": "agent2", "error": _err_message(err)}

    def agent3_node(state: ThreeAgentState) -> dict[str, Any]:
        try:
            knowledge_raw = state.get("code_knowledge")
            if knowledge_raw is None:
                return {
                    "ok": False,
                    "stage": "agent3",
                    "error": "code-knowledge required for Agent-3",
                }
            batch = require_defect_batch(state["defect_batch"])
            knowledge = require_code_knowledge(knowledge_raw)
            call_kwargs: dict[str, Any] = {
                "work_dir": state["work_dir"],
                "defect_batch": batch,
                "code_knowledge": knowledge,
                "open_mr": bool(state.get("open_mr")),
            }
            if state.get("analyze_mode"):
                call_kwargs["analyze_mode"] = state["analyze_mode"]
            try:
                report = analyst(**call_kwargs)
            except TypeError:
                call_kwargs.pop("analyze_mode", None)
                report = analyst(**call_kwargs)
            validated = require_analysis_report(
                report.model_dump() if hasattr(report, "model_dump") else report
            )
            return {
                "analysis_report": validated.model_dump(),
                "ok": True,
                "stage": "done",
                "error": None,
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "stage": "agent3", "error": _err_message(err)}

    def after_agent1(state: ThreeAgentState) -> Literal["agent2", "agent3", "__end__"]:
        if not state.get("ok", True):
            return END
        if state.get("skip_agent2") and state.get("skip_agent3"):
            return END
        if state.get("skip_agent2"):
            return "agent3"
        return "agent2"

    def after_agent2(state: ThreeAgentState) -> Literal["agent3", "__end__"]:
        if not state.get("ok", True):
            return END
        if state.get("skip_agent3"):
            return END
        return "agent3"

    builder = StateGraph(ThreeAgentState)
    builder.add_node("agent1", agent1_node)
    builder.add_node("agent2", agent2_node)
    builder.add_node("agent3", agent3_node)
    builder.add_edge(START, "agent1")
    builder.add_conditional_edges(
        "agent1",
        after_agent1,
        {"agent2": "agent2", "agent3": "agent3", END: END},
    )
    builder.add_conditional_edges(
        "agent2",
        after_agent2,
        {"agent3": "agent3", END: END},
    )
    builder.add_edge("agent3", END)
    return builder.compile()


def _err_message(err: BaseException) -> str:
    if isinstance(err, ArtifactValidationError):
        return str(err)
    return str(err)


# Default compiled graph (no injectable overrides).
default_three_agent_graph = create_three_agent_graph()
