from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Union

from bugfix_agent.contracts import AnalysisReport, CodeKnowledge, DefectBatch
from bugfix_agent.workflow.gates import ArtifactValidationError
from bugfix_agent.workflow.graph import (
    AnalystFn,
    CartographerFn,
    create_three_agent_graph,
    default_three_agent_graph,
)
from bugfix_agent.workflow.state import ThreeAgentState


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
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
) -> ThreeAgentWorkflowResult:
    """Parent workflow via LangGraph: validate → agent → validate. Loose coupling only."""
    if source is None and defect_batch is None:
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent1",
            error="source or defect_batch is required",
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
    if source is not None:
        initial["source"] = str(source) if isinstance(source, Path) else source
    if defect_batch is not None:
        initial["defect_batch"] = defect_batch.model_dump()

    graph = (
        create_three_agent_graph(agent2=agent2, agent3=agent3)
        if agent2 is not None or agent3 is not None
        else default_three_agent_graph
    )

    try:
        final: ThreeAgentState = graph.invoke(initial)
    except Exception as err:  # noqa: BLE001 — surface as workflow failure
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent1",
            error=str(err),
        )

    return _result_from_state(final)


def _result_from_state(state: ThreeAgentState) -> ThreeAgentWorkflowResult:
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

    stage = state.get("stage") or "agent1"
    return ThreeAgentWorkflowResult(
        ok=bool(state.get("ok")) and stage == "done",
        stage=stage,  # type: ignore[arg-type]
        artifacts=artifacts,
        error=state.get("error"),
    )


# Re-export for callers that type-check injectable hooks.
__all__ = [
    "WorkflowArtifacts",
    "ThreeAgentWorkflowResult",
    "run_three_agent_workflow",
    "CartographerFn",
    "AnalystFn",
    "ArtifactValidationError",
]
