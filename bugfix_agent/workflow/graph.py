"""LangGraph parent graph: three agents + explicit validate gates.

Topology (static edges + Command routing from validate_* nodes)::

    START
      │
      ▼
    agent1  ──►  validate_batch  ──Command──►  agent2 | END
                                                  │
                                                  ▼
                                            validate_knowledge ──► agent3 | END
                                                                      │
                                                                      ▼
                                                                validate_report ──► END

Responsibilities
----------------
- ``agent1`` / ``agent2`` / ``agent3``: call the segment ``run_*`` API, write
  artifact dicts into state.
- ``validate_*``: Pydantic hard gate, optional disk persist, decide next hop
  via ``Command(goto=...)`` (no separate conditional_edges map).
- ``RetryPolicy`` on agent nodes: transient I/O / SDK failures only; schema and
  ``ValueError`` / ``TypeError`` are not retried.

Injectable ``agent2`` / ``agent3`` are closed over at compile time so callables
never enter checkpointed state (keeps threads JSON-serializable).
"""

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
    """Compile the parent StateGraph.

    Parameters
    ----------
    agent2 / agent3:
        Optional stubs for unit tests. Default = real cartographer / analyst.
    checkpointer:
        e.g. ``InMemorySaver()`` for durable thread runs. Omit for LangGraph
        Server (platform supplies persistence — see ``langgraph_app.py``).
    retry_policy:
        Attached to agent1/2/3 nodes; validate_* gates are not retried.
    """
    cartographer = agent2 or run_cartographer
    analyst = agent3 or run_analyst

    # ----- Agent-1: ingest / distill / screen / cluster → defect-batch -----
    def agent1_node(state: ThreeAgentState) -> dict[str, Any]:
        # Deterministic rules pipeline: surface data errors as ok=False rather
        # than burning RetryPolicy attempts.
        try:
            existing = state.get("defect_batch")
            if existing is not None:
                # Preloaded batch (HTTP/CLI may pass a finished Agent-1 artifact).
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

    # ----- Gate: defect-batch schema + route to Agent-2 or END -----
    def validate_batch(
        state: ThreeAgentState,
    ) -> Command[Literal["agent2", "__end__"]]:
        if not state.get("ok", True):
            # Agent-1 already recorded stage/error; just stop.
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
            # Debug path: Agent-1 only.
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

    # ----- Agent-2: repo cartography + soft path match → code-knowledge -----
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
            # Injected stubs in tests may not accept cartography_mode.
            call_kwargs.pop("cartography_mode", None)
            knowledge = cartographer(**call_kwargs)
        # Let unexpected cartographer failures raise → RetryPolicy may retry.
        # Output schema is checked in validate_knowledge (not here).
        raw = knowledge.model_dump() if hasattr(knowledge, "model_dump") else knowledge
        return {
            "code_knowledge": raw,
            "ok": True,
            "stage": "agent2",
            "error": None,
        }

    # ----- Gate: code-knowledge schema + route to Agent-3 or END -----
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

    # ----- Agent-3: per-ticket route + optional analyze → analysis-report -----
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

    # ----- Gate: analysis-report schema + mark stage=done -----
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

    # Linear agent → gate edges; validate_* choose the next hop via Command.
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
# Prefer this for one-shot CLI/library invokes; rebuild when checkpointer or
# agent stubs are required.
default_three_agent_graph = create_three_agent_graph()
