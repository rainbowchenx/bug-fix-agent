"""LangGraph 父图：三 Agent + 显式校验门禁。

拓扑（静态边 + validate_* 节点用 Command 路由）::

    START
      │
      ▼
    agent1  ──►  validate_batch  ──Command──►  agent2 | END
                                                  │
                                                  ▼
                                            validate_knowledge ──► agent3 | END
                                                                      │
                                                                      ▼
                                                                validate_report ──► END

职责分工
--------
- ``agent1`` / ``agent2`` / ``agent3``：调用各段 ``run_*``，把产物 dict 写入 state。
- ``validate_*``：Pydantic 硬门禁、可选落盘，用 ``Command(goto=...)`` 决定下一跳
  （不再单独维护 conditional_edges 映射表）。
- Agent 节点挂 ``RetryPolicy``：仅重试瞬时 I/O / SDK 失败；schema 与
  ``ValueError`` / ``TypeError`` 不重试。

可注入的 ``agent2`` / ``agent3`` 在 compile 时闭包捕获，避免把不可序列化
callable 放进 checkpoint state。
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from bugfix_agent.agents.analyst import run_analyst
from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.contracts import CodeKnowledge
from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.workflow.gates import (
    ArtifactValidationError,
    require_analysis_report,
    require_code_knowledge,
    require_defect_batch,
)
from bugfix_agent.workflow.persist import persist_artifact
from bugfix_agent.workflow.state import ThreeAgentState

CartographerFn = Callable[..., CodeKnowledge]
AnalystFn = Callable[..., Any]

# 瞬时失败（I/O、SDK 子进程）短重试；schema / 业务错误绝不空转。
_AGENT_RETRY = RetryPolicy(
    max_attempts=2,
    initial_interval=0.5,
    backoff_factor=2.0,
    retry_on=lambda exc: not isinstance(exc, (ArtifactValidationError, ValueError, TypeError)),
)


def create_three_agent_graph(
    *,
    agent2: Optional[CartographerFn] = None,
    agent3: Optional[AnalystFn] = None,
    checkpointer: Any = None,
    retry_policy: Optional[RetryPolicy | Sequence[RetryPolicy]] = _AGENT_RETRY,
):
    """编译父级 StateGraph。

    Parameters
    ----------
    agent2 / agent3:
        单测可注入的桩；默认走真实 cartographer / analyst。
    checkpointer:
        如 ``InMemorySaver()``，用于按 thread 持久化。LangGraph Server 部署时
        不要挂本地 saver（见 ``langgraph_app.py``）。
    retry_policy:
        挂在 agent1/2/3 上；validate_* 门禁不做重试。
    """
    cartographer = agent2 or run_cartographer
    analyst = agent3 or run_analyst

    # ----- Agent-1：拉取/蒸馏/筛选/分簇 → defect-batch -----
    def agent1_node(state: ThreeAgentState) -> dict[str, Any]:
        # 确定性规则管线：数据错误写成 ok=False，避免白白消耗 RetryPolicy。
        try:
            existing = state.get("defect_batch")
            if existing is not None:
                # 已预置 batch（HTTP/CLI 可能直接传入 Agent-1 产物）。
                return {
                    "defect_batch": existing,
                    "ok": True,
                    "stage": "agent1",
                    "error": None,
                }
            source = state.get("source")
            if source is None:
                return {
                    "ok": False,
                    "stage": "agent1",
                    "error": "source or defect_batch is required",
                }
            prepared = run_defect_batch_prepare(
                product_line=state["product_line"],
                mode="preloaded",
                source=source,
                posture=state.get("posture") or "beta",
            )
            return {
                "defect_batch": prepared.model_dump(),
                "ok": True,
                "stage": "agent1",
                "error": None,
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "stage": "agent1", "error": _err_message(err)}

    # ----- 门禁：defect-batch schema，并路由到 Agent-2 或 END -----
    def validate_batch(
        state: ThreeAgentState,
    ) -> Command[Literal["agent2", "__end__"]]:
        if not state.get("ok", True):
            # Agent-1 已写好 stage/error，直接停。
            return Command(goto=END)
        try:
            batch = require_defect_batch(state.get("defect_batch"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent1", "error": _err_message(err)},
                goto=END,
            )

        dumped = batch.model_dump()
        persist_artifact(state.get("artifact_dir"), "defect-batch.json", dumped)

        both_skip = bool(state.get("skip_agent2")) and bool(state.get("skip_agent3"))
        if both_skip:
            # 调试路径：只跑 Agent-1。
            return Command(
                update={
                    "defect_batch": dumped,
                    "ok": True,
                    "stage": "done",
                    "error": None,
                },
                goto=END,
            )
        # 单独 skip_agent2 已在 run_three_agent_workflow 拒绝；此处 END 为兜底。
        if state.get("skip_agent2"):
            return Command(
                update={
                    "defect_batch": dumped,
                    "ok": False,
                    "stage": "agent2",
                    "error": (
                        "skip_agent2 without skip_agent3 is unsupported "
                        "(Agent-3 needs code-knowledge)"
                    ),
                },
                goto=END,
            )
        return Command(
            update={
                "defect_batch": dumped,
                "ok": True,
                "stage": "agent1",
                "error": None,
            },
            goto="agent2",
        )

    # ----- Agent-2：仓型探测 + 软路径匹配 → code-knowledge -----
    def agent2_node(state: ThreeAgentState) -> dict[str, Any]:
        try:
            batch = require_defect_batch(state["defect_batch"])
        except ArtifactValidationError as err:
            return {"ok": False, "stage": "agent2", "error": _err_message(err)}
        call_kwargs: dict[str, Any] = {
            "work_dir": state["work_dir"],
            "defect_batch": batch,
        }
        if state.get("cartography_mode"):
            call_kwargs["cartography_mode"] = state["cartography_mode"]
        try:
            knowledge = cartographer(**call_kwargs)
        except TypeError:
            # 单测注入的桩可能不接受 cartography_mode。
            call_kwargs.pop("cartography_mode", None)
            knowledge = cartographer(**call_kwargs)
        # 未预期异常向上抛，交给 RetryPolicy；出口 schema 由 validate_knowledge 把关。
        raw = knowledge.model_dump() if hasattr(knowledge, "model_dump") else knowledge
        return {
            "code_knowledge": raw,
            "ok": True,
            "stage": "agent2",
            "error": None,
        }

    # ----- 门禁：code-knowledge schema，并路由到 Agent-3 或 END -----
    def validate_knowledge(
        state: ThreeAgentState,
    ) -> Command[Literal["agent3", "__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            validated = require_code_knowledge(state.get("code_knowledge"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent2", "error": _err_message(err)},
                goto=END,
            )

        dumped = validated.model_dump()
        persist_artifact(state.get("artifact_dir"), "code-knowledge.json", dumped)

        if state.get("skip_agent3"):
            return Command(
                update={
                    "code_knowledge": dumped,
                    "ok": True,
                    "stage": "done",
                    "error": None,
                },
                goto=END,
            )
        return Command(
            update={
                "code_knowledge": dumped,
                "ok": True,
                "stage": "agent2",
                "error": None,
            },
            goto="agent3",
        )

    # ----- Agent-3：按票路由 + 可选 analyze → analysis-report -----
    def agent3_node(state: ThreeAgentState) -> dict[str, Any]:
        knowledge_raw = state.get("code_knowledge")
        if knowledge_raw is None:
            return {
                "ok": False,
                "stage": "agent3",
                "error": "code-knowledge required for Agent-3",
            }
        try:
            batch = require_defect_batch(state["defect_batch"])
            knowledge = require_code_knowledge(knowledge_raw)
        except ArtifactValidationError as err:
            return {"ok": False, "stage": "agent3", "error": _err_message(err)}
        call_kwargs: dict[str, Any] = {
            "work_dir": state["work_dir"],
            "defect_batch": batch,
            "code_knowledge": knowledge,
            "open_mr": bool(state.get("open_mr")),
        }
        if state.get("analyze_mode"):
            call_kwargs["analyze_mode"] = state["analyze_mode"]
        try:
            report = analyst(**call_kwargs)
        except TypeError:
            call_kwargs.pop("analyze_mode", None)
            report = analyst(**call_kwargs)
        # 未预期异常向上抛，交给 RetryPolicy。
        raw = report.model_dump() if hasattr(report, "model_dump") else report
        return {
            "analysis_report": raw,
            "ok": True,
            "stage": "agent3",
            "error": None,
        }

    # ----- 门禁：analysis-report schema，并标记 stage=done -----
    def validate_report(
        state: ThreeAgentState,
    ) -> Command[Literal["__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            validated = require_analysis_report(state.get("analysis_report"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent3", "error": _err_message(err)},
                goto=END,
            )
        dumped = validated.model_dump()
        persist_artifact(state.get("artifact_dir"), "analysis-report.json", dumped)
        return Command(
            update={
                "analysis_report": dumped,
                "ok": True,
                "stage": "done",
                "error": None,
            },
            goto=END,
        )

    builder = StateGraph(ThreeAgentState)
    builder.add_node("agent1", agent1_node, retry_policy=retry_policy)
    builder.add_node("validate_batch", validate_batch)
    builder.add_node("agent2", agent2_node, retry_policy=retry_policy)
    builder.add_node("validate_knowledge", validate_knowledge)
    builder.add_node("agent3", agent3_node, retry_policy=retry_policy)
    builder.add_node("validate_report", validate_report)

    # agent → gate 的线性边；validate_* 用 Command 选择下一跳。
    builder.add_edge(START, "agent1")
    builder.add_edge("agent1", "validate_batch")
    # validate_* 通过 Command(goto=...) 路由，无需静态后继边。
    builder.add_edge("agent2", "validate_knowledge")
    builder.add_edge("agent3", "validate_report")
    return builder.compile(checkpointer=checkpointer)


def _err_message(err: BaseException) -> str:
    if isinstance(err, ArtifactValidationError):
        return str(err)
    return str(err)


# 默认编译图（无注入桩 / 无 checkpointer）。
# 一次性 CLI/库调用优先用它；需要 checkpointer 或 agent 桩时再 rebuild。
default_three_agent_graph = create_three_agent_graph()
