from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

from bugfix_agent.contracts import AnalysisReport, CodeKnowledge, DefectBatch
from bugfix_agent.workflow.gates import ArtifactValidationError
from bugfix_agent.workflow.graph import (
    AnalystFn,
    CartographerFn,
    create_three_agent_graph,
    default_three_agent_graph,
)
from bugfix_agent.workflow.state import ThreeAgentState

WorkflowUpdateFn = Callable[[dict[str, Any]], None]
"""Callback receiving each streamed state snapshot (stream_mode=values)."""


@dataclass
class WorkflowArtifacts:
    defect_batch: Optional[DefectBatch] = None
    code_knowledge: Optional[CodeKnowledge] = None
    analysis_report: Optional[AnalysisReport] = None


@dataclass
class ThreeAgentWorkflowResult:
    ok: bool
    stage: Literal["agent1", "agent2", "agent3", "done"]
    artifacts: WorkflowArtifacts = field(default_factory=WorkflowArtifacts)
    error: Optional[str] = None


def run_three_agent_workflow(
    *,
    work_dir: str | Path,
    product_line: str,
    posture: Literal["alpha", "beta"] = "beta",
    source: Optional[Union[str, Path, dict[str, Any], list[Any]]] = None,
    defect_batch: Optional[DefectBatch] = None,
    open_mr: bool = False,
    skip_agent2: bool = False,
    skip_agent3: bool = False,
    analyze_mode: Optional[Literal["heuristic", "sdk"]] = None,
    cartography_mode: Optional[Literal["heuristic", "sdk"]] = None,
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
    artifact_dir: Optional[str | Path] = None,
    thread_id: Optional[str] = None,
    checkpointer: Any = None,
    on_update: Optional[WorkflowUpdateFn] = None,
) -> ThreeAgentWorkflowResult:
    """Parent workflow via LangGraph: agent → validate gate → next agent.

    - ``artifact_dir``: progressive JSON writes after each successful gate.
    - ``thread_id`` / ``checkpointer``: durable execution (defaults to
      ``InMemorySaver`` when only ``thread_id`` is set).
    - ``on_update``: called with each streamed state value (for HTTP stage polish).
    """
    if source is None and defect_batch is None:
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent1",
            error="source or defect_batch is required",
        )
    if skip_agent2 and not skip_agent3:
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent2",
            error="skip_agent2 without skip_agent3 is unsupported (Agent-3 needs code-knowledge)",
        )

    initial: ThreeAgentState = {
        "work_dir": str(work_dir),
        "product_line": product_line,
        "posture": posture,
        "open_mr": open_mr,
        "skip_agent2": skip_agent2,
        "skip_agent3": skip_agent3,
        "ok": True,
        "stage": "agent1",
        "error": None,
    }
    if analyze_mode is not None:
        initial["analyze_mode"] = analyze_mode
    if cartography_mode is not None:
        initial["cartography_mode"] = cartography_mode
    if source is not None:
        initial["source"] = str(source) if isinstance(source, Path) else source
    if defect_batch is not None:
        initial["defect_batch"] = defect_batch.model_dump()
    if artifact_dir is not None:
        initial["artifact_dir"] = str(artifact_dir)

    needs_custom = (
        agent2 is not None
        or agent3 is not None
        or checkpointer is not None
        or thread_id is not None
    )
    resolved_checkpointer = checkpointer
    if thread_id is not None and resolved_checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        resolved_checkpointer = InMemorySaver()
        needs_custom = True

    graph = (
        create_three_agent_graph(
            agent2=agent2,
            agent3=agent3,
            checkpointer=resolved_checkpointer,
        )
        if needs_custom
        else default_three_agent_graph
    )

    config: Optional[dict[str, Any]] = None
    if resolved_checkpointer is not None:
        config = {"configurable": {"thread_id": thread_id or "bugfix-default"}}

    last_state: Optional[ThreeAgentState] = None
    try:
        if on_update is not None or resolved_checkpointer is not None:
            # Stream values so callers can observe stage transitions; final
            # snapshot is the last values chunk.
            stream_kwargs: dict[str, Any] = {"stream_mode": "values"}
            if config is not None:
                for chunk in graph.stream(initial, config, **stream_kwargs):
                    last_state = chunk  # type: ignore[assignment]
                    if on_update is not None:
                        on_update(dict(chunk))
            else:
                for chunk in graph.stream(initial, **stream_kwargs):
                    last_state = chunk  # type: ignore[assignment]
                    if on_update is not None:
                        on_update(dict(chunk))
            final = last_state if last_state is not None else initial
        else:
            final = graph.invoke(initial, config) if config else graph.invoke(initial)
    except Exception as err:  # noqa: BLE001 — surface as workflow failure
        stage = _stage_from_partial(last_state) if last_state else "agent1"
        artifacts = _artifacts_from_state(last_state) if last_state else WorkflowArtifacts()
        return ThreeAgentWorkflowResult(
            ok=False,
            stage=stage,
            artifacts=artifacts,
            error=str(err),
        )

    return _result_from_state(final)  # type: ignore[arg-type]


def _stage_from_partial(
    state: ThreeAgentState,
) -> Literal["agent1", "agent2", "agent3", "done"]:
    stage = state.get("stage") or "agent1"
    if stage in ("agent1", "agent2", "agent3", "done"):
        return stage  # type: ignore[return-value]
    return "agent1"


def _artifacts_from_state(state: ThreeAgentState) -> WorkflowArtifacts:
    artifacts = WorkflowArtifacts()
    if state.get("defect_batch") is not None:
        try:
            artifacts.defect_batch = DefectBatch.model_validate(state["defect_batch"])
        except Exception:  # noqa: BLE001
            artifacts.defect_batch = None
    if state.get("code_knowledge") is not None:
        try:
            artifacts.code_knowledge = CodeKnowledge.model_validate(state["code_knowledge"])
        except Exception:  # noqa: BLE001
            artifacts.code_knowledge = None
    if state.get("analysis_report") is not None:
        try:
            artifacts.analysis_report = AnalysisReport.model_validate(state["analysis_report"])
        except Exception:  # noqa: BLE001
            artifacts.analysis_report = None
    return artifacts


def _result_from_state(state: ThreeAgentState) -> ThreeAgentWorkflowResult:
    artifacts = _artifacts_from_state(state)
    stage = _stage_from_partial(state)
    return ThreeAgentWorkflowResult(
        ok=bool(state.get("ok")) and stage == "done",
        stage=stage,
        artifacts=artifacts,
        error=state.get("error"),
    )


# Re-export for callers that type-check injectable hooks.
__all__ = [
    "WorkflowArtifacts",
    "ThreeAgentWorkflowResult",
    "WorkflowUpdateFn",
    "run_three_agent_workflow",
    "CartographerFn",
    "AnalystFn",
    "ArtifactValidationError",
]
