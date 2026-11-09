"""Agent-1：图外 defect-batch 制备。不依赖 LangGraph / Agent-2/3。"""

from bugfix_agent1._version import __version__
from bugfix_agent1.defect_batch import prepare_defect_batch, run_defect_batch_prepare
from bugfix_contracts import (
    CONTRACT_SCHEMA_VERSION,
    DEFECT_BATCH_SCHEMA_VERSION,
    DefectBatch,
    validate_defect_batch,
)

__all__ = [
    "__version__",
    "CONTRACT_SCHEMA_VERSION",
    "DEFECT_BATCH_SCHEMA_VERSION",
    "DefectBatch",
    "validate_defect_batch",
    "prepare_defect_batch",
    "run_defect_batch_prepare",
]
