"""LangGraph 平台：Agent-2 cartographer → Agent-3 analyst。不含 Agent-1。"""

from bugfix_contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CONTRACT_SCHEMA_VERSION,
    DEFECT_BATCH_SCHEMA_VERSION,
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    validate_analysis_report,
    validate_code_knowledge,
    validate_defect_batch,
)
from bugfix_platform._version import __version__
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.workflow import create_three_agent_graph, run_three_agent_workflow

__all__ = [
    "__version__",
    "CONTRACT_SCHEMA_VERSION",
    "DEFECT_BATCH_SCHEMA_VERSION",
    "CODE_KNOWLEDGE_SCHEMA_VERSION",
    "ANALYSIS_REPORT_SCHEMA_VERSION",
    "DefectBatch",
    "CodeKnowledge",
    "AnalysisReport",
    "validate_defect_batch",
    "validate_code_knowledge",
    "validate_analysis_report",
    "run_cartographer",
    "run_analyst",
    "run_three_agent_workflow",
    "create_three_agent_graph",
]
