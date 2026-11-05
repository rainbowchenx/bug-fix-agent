from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

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
from bugfix_agent.workflow.persist import persist_artifact
from bugfix_agent.workflow.state import ThreeAgentState

CartographerFn = Callable[..., CodeKnowledge]
AnalystFn = Callable[..., Any]

# Transient failures (I/O, SDK subprocess) get a short retry; schema/business
# errors must not spin.
_AGENT_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=0.5,
    backoff_factor=2.0,
    retry_on=lambda exc: not isinstance(exc, (ArtifactValidationError, ValueError, TypeError)),
)


def create_three_agent_graph(
    *,
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
    checkpointer: Any = None,
    retry_policy: Optional[RetryPolicy | Sequence[RetryPolicy]] = _AGENT_RETRY,
):
    """Build the parent LangGraph matching the architecture gates:

    ``agent1 → validate_batch → agent2 → validate_knowledge → agent3 → validate_report``

    Agent callables are closed over so tests can inject stubs without putting
    non-serializable callables into checkpoint state. Pass ``checkpointer``
    (e.g. ``InMemorySaver()``) for durable / thread-scoped runs; omit it for
    LangGraph Server which supplies its own.
    """
    cartographer = agent2 or run_cartographer
    analyst = agent3 or run_analyst

    def agent1_node(state: ThreeAgentState) -> dict[str, Any]:
        # Deterministic rules pipeline: surface data errors as ok=False rather
        # than burning RetryPolicy attempts.
        try:
            existing = state.get("defect_batch")
            if existing is not None:
                return {
                    "defect_batch": existing,
                    "ok": True,
                    "stage": "agent1",
                    "error": None,
                }
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
            return {
                "defect_batch": prepared.model_dump(),
                "ok": True,
                "stage": "agent1",
                "error": None,
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "stage": "agent1", "error": _err_message(err)}

    def validate_batch(
        state: ThreeAgentState,
    ) -> Command[Literal["agent2", "__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            batch = require_defect_batch(state.get("defect_batch"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent1", "error": _err_message(err)},
                goto=END,
            )

        dumped = batch.model_dump()
        persist_artifact(state.get("artifact_dir"), "defect-batch.json", dumped)

        both_skip = bool(state.get("skip_agent2")) and bool(state.get("skip_agent3"))
        if both_skip:
            return Command(
                update={
                    "defect_batch": dumped,
                    "ok": True,
                    "stage": "done",
                    "error": None,
                },
                goto=END,
            )
        # skip_agent2 alone is rejected in run_three_agent_workflow; END is safety net.
        if state.get("skip_agent2"):
            return Command(
                update={
                    "defect_batch": dumped,
                    "ok": False,
                    "stage": "agent2",
                    "error": (
                        "skip_agent2 without skip_agent3 is unsupported "
                        "(Agent-3 needs code-knowledge)"
                    ),
                },
                goto=END,
            )
        return Command(
            update={
                "defect_batch": dumped,
                "ok": True,
                "stage": "agent1",
                "error": None,
            },
            goto="agent2",
        )

    def agent2_node(state: ThreeAgentState) -> dict[str, Any]:
        try:
            batch = require_defect_batch(state["defect_batch"])
        except ArtifactValidationError as err:
            return {"ok": False, "stage": "agent2", "error": _err_message(err)}
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
        # Let unexpected cartographer failures raise → RetryPolicy may retry.
        raw = knowledge.model_dump() if hasattr(knowledge, "model_dump") else knowledge
        return {
            "code_knowledge": raw,
            "ok": True,
            "stage": "agent2",
            "error": None,
        }

    def validate_knowledge(
        state: ThreeAgentState,
    ) -> Command[Literal["agent3", "__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            validated = require_code_knowledge(state.get("code_knowledge"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent2", "error": _err_message(err)},
                goto=END,
            )

        dumped = validated.model_dump()
        persist_artifact(state.get("artifact_dir"), "code-knowledge.json", dumped)

        if state.get("skip_agent3"):
            return Command(
                update={
                    "code_knowledge": dumped,
                    "ok": True,
                    "stage": "done",
                    "error": None,
                },
                goto=END,
            )
        return Command(
            update={
                "code_knowledge": dumped,
                "ok": True,
                "stage": "agent2",
                "error": None,
            },
            goto="agent3",
        )

    def agent3_node(state: ThreeAgentState) -> dict[str, Any]:
        knowledge_raw = state.get("code_knowledge")
        if knowledge_raw is None:
            return {
                "ok": False,
                "stage": "agent3",
                "error": "code-knowledge required for Agent-3",
            }
        try:
            batch = require_defect_batch(state["defect_batch"])
            knowledge = require_code_knowledge(knowledge_raw)
        except ArtifactValidationError as err:
            return {"ok": False, "stage": "agent3", "error": _err_message(err)}
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
        # Let unexpected analyst failures raise → RetryPolicy may retry.
        raw = report.model_dump() if hasattr(report, "model_dump") else report
        return {
            "analysis_report": raw,
            "ok": True,
            "stage": "agent3",
            "error": None,
        }

    def validate_report(
        state: ThreeAgentState,
    ) -> Command[Literal["__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            validated = require_analysis_report(state.get("analysis_report"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent3", "error": _err_message(err)},
                goto=END,
            )
        dumped = validated.model_dump()
        persist_artifact(state.get("artifact_dir"), "analysis-report.json", dumped)
        return Command(
            update={
                "analysis_report": dumped,
                "ok": True,
                "stage": "done",
                "error": None,
            },
            goto=END,
        )

    builder = StateGraph(ThreeAgentState)
    builder.add_node("agent1", agent1_node, retry_policy=retry_policy)
    builder.add_node("validate_batch", validate_batch)
    builder.add_node("agent2", agent2_node, retry_policy=retry_policy)
    builder.add_node("validate_knowledge", validate_knowledge)
    builder.add_node("agent3", agent3_node, retry_policy=retry_policy)
    builder.add_node("validate_report", validate_report)

    builder.add_edge(START, "agent1")
    builder.add_edge("agent1", "validate_batch")
    # validate_* nodes route via Command(goto=...); no static edges needed.
    builder.add_edge("agent2", "validate_knowledge")
    builder.add_edge("agent3", "validate_report")
    return builder.compile(checkpointer=checkpointer)


def _err_message(err: BaseException) -> str:
    if isinstance(err, ArtifactValidationError):
        return str(err)
    return str(err)


# Default compiled graph (no injectable overrides / no checkpointer).
default_three_agent_graph = create_three_agent_graph()
