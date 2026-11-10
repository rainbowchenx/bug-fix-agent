"""Cross-agent contracts — the ONLY allowed coupling surface."""

from bugfix_contracts.env import ENV_FILE_VAR, load_env_file
from bugfix_contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    MATCH_POOLS,
    Confidence,
    MatchPool,
    is_match_pool,
)
from bugfix_contracts.defect_batch import (
    DEFECT_BATCH_SCHEMA_VERSION,
    BatchCluster,
    BatchTicket,
    DefectBatch,
    ExpectQuality,
    Intent,
    Pool,
    RawDefect,
    RawDefectsFile,
    safe_validate_defect_batch,
    validate_defect_batch,
)
from bugfix_contracts.code_knowledge import (
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    CartographyProfile,
    CodeKnowledge,
    DefectCodeMatch,
    MatchCandidate,
    safe_validate_code_knowledge,
    validate_code_knowledge,
)
from bugfix_contracts.analysis_report import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    AnalysisReport,
    TicketBlockers,
    TicketOutcome,
    TicketReport,
    safe_validate_analysis_report,
    validate_analysis_report,
)

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "MATCH_POOLS",
    "Confidence",
    "MatchPool",
    "is_match_pool",
    "DEFECT_BATCH_SCHEMA_VERSION",
    "DefectBatch",
    "BatchTicket",
    "BatchCluster",
    "Pool",
    "Intent",
    "ExpectQuality",
    "RawDefect",
    "RawDefectsFile",
    "validate_defect_batch",
    "safe_validate_defect_batch",
    "CODE_KNOWLEDGE_SCHEMA_VERSION",
    "CodeKnowledge",
    "CartographyProfile",
    "DefectCodeMatch",
    "MatchCandidate",
    "validate_code_knowledge",
    "safe_validate_code_knowledge",
    "ANALYSIS_REPORT_SCHEMA_VERSION",
    "AnalysisReport",
    "TicketReport",
    "TicketOutcome",
    "TicketBlockers",
    "validate_analysis_report",
    "safe_validate_analysis_report",
]
