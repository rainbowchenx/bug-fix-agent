from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class ThreeAgentState(TypedDict):
    """LangGraph shared state for Agent-1 → Agent-2 → Agent-3.

    Design notes
    ------------
    - Artifacts are plain ``dict`` so checkpoints / Studio stay JSON-serializable.
    - Nodes return partial updates; LangGraph merges them into this state.
    - Agents stay loosely coupled: call ``run_*`` + Pydantic gates only — never
      import another agent's private modules.

    Control fields
    --------------
    - ``ok``: soft failure flag. Validate nodes end the run when False.
    - ``stage``: last reached phase (``agent1|agent2|agent3|done``); HTTP polls this.
    - ``error``: human-readable reason when ``ok`` is False.
    """

    # --- run inputs (set once at invoke) ---
    work_dir: str
    product_line: str
    posture: Literal["alpha", "beta"]
    open_mr: bool
    skip_agent2: bool
    skip_agent3: bool
    analyze_mode: NotRequired[Literal["heuristic", "sdk"]]
    cartography_mode: NotRequired[Literal["heuristic", "sdk"]]

    source: NotRequired[Any]
    """raw-defects path / JSON payload for Agent-1 when `defect_batch` is absent."""

    # --- progressive artifacts (dict form of Pydantic models) ---
    defect_batch: NotRequired[dict[str, Any]]
    code_knowledge: NotRequired[dict[str, Any]]
    analysis_report: NotRequired[dict[str, Any]]

    artifact_dir: NotRequired[str]
    """If set, validate gates write JSON artifacts progressively after each success."""

    # --- control / observability ---
    ok: NotRequired[bool]
    stage: NotRequired[Literal["agent1", "agent2", "agent3", "done"]]
    error: NotRequired[str | None]
