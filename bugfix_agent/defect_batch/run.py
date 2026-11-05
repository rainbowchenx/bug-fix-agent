"""Agent-1 public entry: raw defects → ``defect-batch``.

``preloaded`` mode loads CSV/JSON/xlsx-derived payloads, then runs the
deterministic distill / screen / cluster pipeline (no LLM). ``mcp`` / ``crawler``
ingest modes are stubs until production defect MCP is wired.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Union

from bugfix_agent.contracts.defect_batch import DefectBatch, RawDefect
from bugfix_agent.defect_batch.prepare import prepare_defect_batch
from bugfix_agent.defect_batch.rules import ScreenProfile
from bugfix_agent.ingest.preloaded import load_preloaded


def run_defect_batch_prepare(
    *,
    product_line: str,
    mode: Literal["preloaded", "mcp", "crawler"] = "preloaded",
    source: Optional[Union[str, Path, dict[str, Any], list[Any]]] = None,
    defects: Optional[list[RawDefect]] = None,
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
) -> DefectBatch:
    """Load (optional) + prepare; used by CLI ``prepare-batch`` and graph agent1."""
    if mode != "preloaded":
        raise NotImplementedError(f"ingest mode {mode!r} is stubbed; use preloaded")
    if defects is None:
        if source is None:
            raise ValueError("source or defects is required for preloaded mode")
        defects = load_preloaded(source)
    return prepare_defect_batch(
        product_line=product_line,
        defects=defects,
        posture=posture,
        profile=profile,
    )
