"""调用父级 LangGraph，并把终态映射为 ``ThreeAgentWorkflowResult``。

调用路径
--------
1. **快路径**（默认）：``default_three_agent_graph.invoke(initial)`` —
   无 checkpointer、不流式。
2. **可观测 / 可恢复路径**：传入 ``on_update``、``thread_id`` 或显式
   ``checkpointer`` 时，用 ``stream_mode="values"`` 流式输出，供 HTTP
   刷新 ``stage``，崩溃时也能带回部分产物。

预检（必须有 source、禁止单独 skip_agent2）在进图前完成，非法请求不会
创建 checkpoint 线程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

from bugfix_agent.contracts import AnalysisReport, CodeKnowledge, DefectBatch
from bugfix_agent.workflow.gates import ArtifactValidationError
from bugfix_agent.workflow.graph import (
    AnalystFn,
    CartographerFn,
    create_three_agent_graph,
    default_three_agent_graph,
)
from bugfix_agent.workflow.state import ThreeAgentState

WorkflowUpdateFn = Callable[[dict[str, Any]], None]
"""每帧流式 state 快照的回调（stream_mode=values）。"""


@dataclass
class WorkflowArtifacts:
    """三段跨 Agent JSON 产物的类型化副本（允许部分缺失）。"""

    defect_batch: Optional[DefectBatch] = None
    code_knowledge: Optional[CodeKnowledge] = None
    analysis_report: Optional[AnalysisReport] = None


@dataclass
class ThreeAgentWorkflowResult:
    """面向库 / CLI / HTTP 的运行结果。

    仅当 ``stage == "done"`` 且 state ``ok`` 为 True 时 ``ok`` 才为 True——
    成功的「只跑 Agent-1」跳过路径同样会把 ``stage`` 设为 ``done``。
    """

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
    analyze_mode: Optional[Literal["heuristic", "sdk"]] = None,
    cartography_mode: Optional[Literal["heuristic", "sdk"]] = None,
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
    artifact_dir: Optional[str | Path] = None,
    thread_id: Optional[str] = None,
    checkpointer: Any = None,
    on_update: Optional[WorkflowUpdateFn] = None,
) -> ThreeAgentWorkflowResult:
    """父编排入口：agent → 校验门禁 → 下一 agent。

    - ``artifact_dir``：每个门禁成功后渐进写 JSON。
    - ``thread_id`` / ``checkpointer``：持久化执行（仅给 ``thread_id`` 时
      默认挂 ``InMemorySaver``）。
    - ``on_update``：每帧流式 state（供 HTTP 刷新 stage）。
    """
    # --- 预检（不过图，直接失败关闭） ---
    if source is None and defect_batch is None:
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent1",
            error="source or defect_batch is required",
        )
    if skip_agent2 and not skip_agent3:
        return ThreeAgentWorkflowResult(
            ok=False,
            stage="agent2",
            error="skip_agent2 without skip_agent3 is unsupported (Agent-3 needs code-knowledge)",
        )

    # --- 组装初始 LangGraph state（保持 JSON 友好） ---
    initial: ThreeAgentState = {
        "work_dir": str(work_dir),
        "product_line": product_line,
        "posture": posture,
        "open_mr": open_mr,
        "skip_agent2": skip_agent2,
        "skip_agent3": skip_agent3,
        "ok": True,
        "stage": "agent1",
        "error": None,
    }
    if analyze_mode is not None:
        initial["analyze_mode"] = analyze_mode
    if cartography_mode is not None:
        initial["cartography_mode"] = cartography_mode
    if source is not None:
        initial["source"] = str(source) if isinstance(source, Path) else source
    if defect_batch is not None:
        initial["defect_batch"] = defect_batch.model_dump()
    if artifact_dir is not None:
        initial["artifact_dir"] = str(artifact_dir)

    # 有桩 / checkpointer / thread_id 时需要重新 compile。
    needs_custom = (
        agent2 is not None
        or agent3 is not None
        or checkpointer is not None
        or thread_id is not None
    )
    resolved_checkpointer = checkpointer
    if thread_id is not None and resolved_checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        resolved_checkpointer = InMemorySaver()
        needs_custom = True

    graph = (
        create_three_agent_graph(
            agent2=agent2,
            agent3=agent3,
            checkpointer=resolved_checkpointer,
        )
        if needs_custom
        else default_three_agent_graph
    )

    config: Optional[dict[str, Any]] = None
    if resolved_checkpointer is not None:
        # LangGraph 按 configurable.thread_id 隔离 checkpoint。
        config = {"configurable": {"thread_id": thread_id or "bugfix-default"}}

    last_state: Optional[ThreeAgentState] = None
    try:
        if on_update is not None or resolved_checkpointer is not None:
            # 每节点后流式累计 state，供 HTTP 更新 meta.stage。
            stream_kwargs: dict[str, Any] = {"stream_mode": "values"}
            if config is not None:
                for chunk in graph.stream(initial, config, **stream_kwargs):
                    last_state = chunk  # type: ignore[assignment]
                    if on_update is not None:
                        on_update(dict(chunk))
            else:
                for chunk in graph.stream(initial, **stream_kwargs):
                    last_state = chunk  # type: ignore[assignment]
                    if on_update is not None:
                        on_update(dict(chunk))
            final = last_state if last_state is not None else initial
        else:
            final = graph.invoke(initial, config) if config else graph.invoke(initial)
    except Exception as err:  # noqa: BLE001 — 统一收敛为工作流失败结果
        # 优先用最后一帧流式快照，让 stage/产物反映真实进度。
        stage = _stage_from_partial(last_state) if last_state else "agent1"
        artifacts = _artifacts_from_state(last_state) if last_state else WorkflowArtifacts()
        return ThreeAgentWorkflowResult(
            ok=False,
            stage=stage,
            artifacts=artifacts,
            error=str(err),
        )

    return _result_from_state(final)  # type: ignore[arg-type]


def _stage_from_partial(
    state: ThreeAgentState,
) -> Literal["agent1", "agent2", "agent3", "done"]:
    stage = state.get("stage") or "agent1"
    if stage in ("agent1", "agent2", "agent3", "done"):
        return stage  # type: ignore[return-value]
    return "agent1"


def _artifacts_from_state(state: ThreeAgentState) -> WorkflowArtifacts:
    """尽力从 state dict 还原 Pydantic 模型（部分失败可接受）。"""
    artifacts = WorkflowArtifacts()
    if state.get("defect_batch") is not None:
        try:
            artifacts.defect_batch = DefectBatch.model_validate(state["defect_batch"])
        except Exception:  # noqa: BLE001
            artifacts.defect_batch = None
    if state.get("code_knowledge") is not None:
        try:
            artifacts.code_knowledge = CodeKnowledge.model_validate(state["code_knowledge"])
        except Exception:  # noqa: BLE001
            artifacts.code_knowledge = None
    if state.get("analysis_report") is not None:
        try:
            artifacts.analysis_report = AnalysisReport.model_validate(state["analysis_report"])
        except Exception:  # noqa: BLE001
            artifacts.analysis_report = None
    return artifacts


def _result_from_state(state: ThreeAgentState) -> ThreeAgentWorkflowResult:
    artifacts = _artifacts_from_state(state)
    stage = _stage_from_partial(state)
    return ThreeAgentWorkflowResult(
        ok=bool(state.get("ok")) and stage == "done",
        stage=stage,
        artifacts=artifacts,
        error=state.get("error"),
    )


# 供需要类型标注注入钩子的调用方再导出。
__all__ = [
    "WorkflowArtifacts",
    "ThreeAgentWorkflowResult",
    "WorkflowUpdateFn",
    "run_three_agent_workflow",
    "CartographerFn",
    "AnalystFn",
    "ArtifactValidationError",
]
