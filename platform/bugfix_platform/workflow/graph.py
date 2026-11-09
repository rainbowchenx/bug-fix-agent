"""LangGraph 父图：Agent-2 → Agent-3 + 显式校验门禁。

Agent-1（defect-batch 准备）在图外：由 ``prepare-batch`` / ``defect-batch-prepare``
skill + Claude Code 产出，调用方必须把已校验的 ``defect_batch`` 写入初始 state。

拓扑（静态边 + validate_* 节点用 Command 路由）::

    START
      │
      ▼
    validate_batch  ──Command──►  agent2 | END
                                     │
                                     ▼
                               validate_knowledge ──► agent3 | END
                                                         │
                                                         ▼
                                                   validate_report ──► END

职责分工
--------
- ``validate_batch``：入口硬门禁（要求已有 defect-batch），再进 Agent-2。
- ``agent2`` / ``agent3``：调用各段 ``run_*``，把产物 dict 写入 state。
- ``validate_*``：Pydantic 硬门禁、可选落盘，用 ``Command(goto=...)`` 决定下一跳。
- Agent 节点挂 ``RetryPolicy``：仅重试瞬时 I/O / SDK 失败；schema 与
  ``ValueError`` / ``TypeError`` 不重试。

可注入的 ``agent2`` / ``agent3`` 在 compile 时闭包捕获，避免把不可序列化
callable 放进 checkpoint state。
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_contracts import CodeKnowledge
from bugfix_platform.workflow.gates import (
    ArtifactValidationError,
    require_analysis_report,
    require_code_knowledge,
    require_defect_batch,
)
from bugfix_platform.workflow.persist import persist_artifact
from bugfix_platform.workflow.state import ThreeAgentState

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
    """编译父级 StateGraph（仅 Agent-2 / Agent-3）。

    Parameters
    ----------
    agent2 / agent3:
        单测可注入的桩；默认走真实 cartographer / analyst。
    checkpointer:
        如 ``InMemorySaver()``，用于按 thread 持久化。LangGraph Server 部署时
        不要挂本地 saver（见 ``langgraph_app.py``）。
    retry_policy:
        挂在 agent2/3 上；validate_* 门禁不做重试。
    """
    cartographer = agent2 or run_cartographer
    analyst = agent3 or run_analyst

    # ----- 入口门禁：要求图外 Agent-1 已产出 defect-batch -----
    def validate_batch(
        state: ThreeAgentState,
    ) -> Command[Literal["agent2", "__end__"]]:
        if not state.get("ok", True):
            return Command(goto=END)
        try:
            batch = require_defect_batch(state.get("defect_batch"))
        except ArtifactValidationError as err:
            return Command(
                update={"ok": False, "stage": "agent2", "error": _err_message(err)},
                goto=END,
            )

        dumped = batch.model_dump()
        persist_artifact(state.get("artifact_dir"), "defect-batch.json", dumped)

        both_skip = bool(state.get("skip_agent2")) and bool(state.get("skip_agent3"))
        if both_skip:
            # 调试路径：只校验 ingress batch，不跑 2/3。
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
                "stage": "agent2",
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
        if state.get("extra_skill_dirs"):
            call_kwargs["extra_skill_dirs"] = state["extra_skill_dirs"]
        try:
            knowledge = cartographer(**call_kwargs)
        except TypeError:
            # 单测注入的桩可能不接受 cartography_mode / extra_skill_dirs。
            call_kwargs.pop("cartography_mode", None)
            try:
                knowledge = cartographer(**call_kwargs)
            except TypeError:
                call_kwargs.pop("extra_skill_dirs", None)
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
        if state.get("extra_skill_dirs"):
            call_kwargs["extra_skill_dirs"] = state["extra_skill_dirs"]
        try:
            report = analyst(**call_kwargs)
        except TypeError:
            # 单测注入的桩可能不接受 analyze_mode / extra_skill_dirs。
            call_kwargs.pop("analyze_mode", None)
            try:
                report = analyst(**call_kwargs)
            except TypeError:
                call_kwargs.pop("extra_skill_dirs", None)
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
    builder.add_node("validate_batch", validate_batch)
    builder.add_node("agent2", agent2_node, retry_policy=retry_policy)
    builder.add_node("validate_knowledge", validate_knowledge)
    builder.add_node("agent3", agent3_node, retry_policy=retry_policy)
    builder.add_node("validate_report", validate_report)

    # 入口直接校验已有 defect-batch；validate_* 用 Command 选择下一跳。
    builder.add_edge(START, "validate_batch")
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
