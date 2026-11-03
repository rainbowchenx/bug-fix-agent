from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.contracts import AnalysisReport, CodeKnowledge, DefectBatch
from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.workflow.gates import (
    ArtifactValidationError,
    require_analysis_report,
    require_code_knowledge,
    require_defect_batch,
)

CartographerFn = Callable[..., CodeKnowledge]
AnalystFn = Callable[..., AnalysisReport]


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
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
) -> ThreeAgentWorkflowResult:
    """Parent workflow: validate → agent → validate. Loose coupling only."""
    artifacts = WorkflowArtifacts()
    work_dir = str(work_dir)

    try:
        batch = defect_batch
        if batch is None:
            if source is None:
                return ThreeAgentWorkflowResult(
                    ok=False, stage="agent1", error="source or defect_batch is required", artifacts=artifacts
                )
            batch = run_defect_batch_prepare(
                product_line=product_line,
                mode="preloaded",
                source=source,
                posture=posture,
            )
        artifacts.defect_batch = require_defect_batch(batch.model_dump())

        if skip_agent2 and skip_agent3:
            return ThreeAgentWorkflowResult(ok=True, stage="done", artifacts=artifacts)

        if not skip_agent2:
            fn2 = agent2 or run_cartographer
            knowledge = fn2(work_dir=work_dir, defect_batch=artifacts.defect_batch)
            artifacts.code_knowledge = require_code_knowledge(
                knowledge.model_dump() if hasattr(knowledge, "model_dump") else knowledge
            )

        if skip_agent3:
            return ThreeAgentWorkflowResult(ok=True, stage="done", artifacts=artifacts)

        if artifacts.code_knowledge is None:
            return ThreeAgentWorkflowResult(
                ok=False,
                stage="agent3",
                error="code-knowledge required for Agent-3",
                artifacts=artifacts,
            )

        fn3 = agent3 or run_analyst
        report = fn3(
            work_dir=work_dir,
            defect_batch=artifacts.defect_batch,
            code_knowledge=artifacts.code_knowledge,
            open_mr=open_mr,
        )
        artifacts.analysis_report = require_analysis_report(
            report.model_dump() if hasattr(report, "model_dump") else report
        )
        return ThreeAgentWorkflowResult(ok=True, stage="done", artifacts=artifacts)
    except Exception as err:  # noqa: BLE001
        stage: Literal["agent1", "agent2", "agent3"] = (
            "agent1"
            if artifacts.defect_batch is None
            else "agent2"
            if artifacts.code_knowledge is None
            else "agent3"
        )
        message = str(err) if isinstance(err, ArtifactValidationError) else str(err)
        return ThreeAgentWorkflowResult(ok=False, stage=stage, error=message, artifacts=artifacts)
