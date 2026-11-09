"""父级 LangGraph 编排（仅 Agent-2 → Agent-3）。

Agent-1（defect-batch）在图外：``prepare-batch`` / skill + Claude Code。

对外入口：``run_three_agent_workflow``（CLI / HTTP / 库调用）。
构图工厂：``create_three_agent_graph``（单测、LangGraph Server）。

流程（松耦合——Agent 之间只交换校验后的 JSON 产物）::

    defect_batch（图外 Agent-1）
            │
            ▼
    validate_batch ──► agent2 ──► validate_knowledge ──► agent3 ──► validate_report ──► done

硬门禁：任一 ``ok=False`` 或 Pydantic 校验失败，图在该 stage 结束
（不越过红灯继续交付）。
"""

from bugfix_platform.workflow.gates import ArtifactValidationError
from bugfix_platform.workflow.graph import create_three_agent_graph, default_three_agent_graph
from bugfix_platform.workflow.run import (
    ThreeAgentWorkflowResult,
    WorkflowArtifacts,
    WorkflowUpdateFn,
    load_defect_batch,
    run_three_agent_workflow,
)

__all__ = [
    "run_three_agent_workflow",
    "load_defect_batch",
    "ThreeAgentWorkflowResult",
    "WorkflowArtifacts",
    "WorkflowUpdateFn",
    "create_three_agent_graph",
    "default_three_agent_graph",
    "ArtifactValidationError",
]
