from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class ThreeAgentState(TypedDict):
    """LangGraph state for Agent-1 → Agent-2 → Agent-3.

    Artifacts are stored as plain dicts so checkpoints stay JSON-serializable.
    Agents remain loosely coupled: nodes only call `run_*` + Pydantic gates.
    """

    work_dir: str
    product_line: str
    posture: Literal["alpha", "beta"]
    open_mr: bool
    skip_agent2: bool
    skip_agent3: bool

    source: NotRequired[Any]
    """raw-defects path / JSON payload for Agent-1 when `defect_batch` is absent."""

    defect_batch: NotRequired[dict[str, Any]]
    code_knowledge: NotRequired[dict[str, Any]]
    analysis_report: NotRequired[dict[str, Any]]

    ok: NotRequired[bool]
    stage: NotRequired[Literal["agent1", "agent2", "agent3", "done"]]
    error: NotRequired[str | None]
