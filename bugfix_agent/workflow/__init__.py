"""Parent LangGraph orchestration for the three-agent defect pipeline.

Public entry: ``run_three_agent_workflow`` (CLI / HTTP / library).
Graph factory: ``create_three_agent_graph`` (tests, LangGraph Server).

Flow (loose coupling — agents only exchange validated JSON artifacts)::

    source / defect_batch
            │
            ▼
       agent1 ──► validate_batch ──► agent2 ──► validate_knowledge
                                                    │
                                                    ▼
                                              agent3 ──► validate_report ──► done

Hard stop: any ``ok=False`` or Pydantic gate failure ends the graph at that stage
(no MR / no partial delivery past a red gate).
"""

from bugfix_agent.workflow.gates import ArtifactValidationError
from bugfix_agent.workflow.graph import create_three_agent_graph, default_three_agent_graph
from bugfix_agent.workflow.run import (
    ThreeAgentWorkflowResult,
    WorkflowArtifacts,
    WorkflowUpdateFn,
    run_three_agent_workflow,
)

__all__ = [
    "run_three_agent_workflow",
    "ThreeAgentWorkflowResult",
    "WorkflowArtifacts",
    "WorkflowUpdateFn",
    "create_three_agent_graph",
    "default_three_agent_graph",
    "ArtifactValidationError",
]
