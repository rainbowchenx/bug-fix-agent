from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class ThreeAgentState(TypedDict):
    """LangGraph 共享状态：Agent-2 → Agent-3。

    Agent-1 在图外：调用方必须提供已准备好的 ``defect_batch``（来自
    ``prepare-batch`` / skill + Claude Code）。

    设计要点
    --------
    - 产物以普通 ``dict`` 存放，便于 checkpoint / Studio 做 JSON 序列化。
    - 节点只返回部分更新；由 LangGraph 合并进本状态。
    - Agent 松耦合：只调用 ``run_*`` + Pydantic 门禁，禁止 import 另一 Agent 私有模块。

    控制字段
    --------
    - ``ok``：软失败标志；校验节点见 False 即结束。
    - ``stage``：当前阶段（``agent2|agent3|done``）；HTTP 轮询读此字段。
    - ``error``：``ok`` 为 False 时的可读原因。
    """

    # --- 运行入参（invoke 时一次性写入） ---
    work_dir: str
    product_line: str
    posture: Literal["alpha", "beta"]
    open_mr: bool
    skip_agent2: bool
    skip_agent3: bool
    analyze_mode: NotRequired[Literal["heuristic", "sdk"]]
    cartography_mode: NotRequired[Literal["heuristic", "sdk"]]

    # --- 渐进产物（Pydantic 模型的 dict 形态） ---
    defect_batch: dict[str, Any]
    """Agent-1 出口（图外准备）；父图入口硬依赖。"""

    code_knowledge: NotRequired[dict[str, Any]]
    analysis_report: NotRequired[dict[str, Any]]

    artifact_dir: NotRequired[str]
    """若设置，各 validate 门禁在校验成功后渐进写入 JSON 产物。"""

    # --- 控制 / 可观测性 ---
    ok: NotRequired[bool]
    stage: NotRequired[Literal["agent2", "agent3", "done"]]
    error: NotRequired[str | None]
