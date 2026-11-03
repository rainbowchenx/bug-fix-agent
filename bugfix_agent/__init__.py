"""Three-agent defect workflow — Python implementation."""

from bugfix_agent.contracts import (
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
from bugfix_agent.defect_batch import prepare_defect_batch, run_defect_batch_prepare
from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.workflow import run_three_agent_workflow

__all__ = [
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
    "prepare_defect_batch",
    "run_defect_batch_prepare",
    "run_cartographer",
    "run_analyst",
    "run_three_agent_workflow",
]

__version__ = "0.2.0"
