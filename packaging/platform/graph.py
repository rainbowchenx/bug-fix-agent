"""平台入口：zip 根级 ``graph.py``。

公司 agent 平台要求 zip 根目录存在 ``graph.py``，并暴露
``build_graph()`` / ``graph`` / ``main()`` 三者之一。这里三个都给。

真正的图定义在 ``bugfix_platform/workflow/langgraph_app.py``，此处只做转发——
不要在两边各写一份 StateGraph，否则漂移后平台和本地跑的不是同一张图。

注意：**不要**在这里挂 ``InMemorySaver``。持久化由平台 Server 负责。
"""

from __future__ import annotations

# 平台只负责 import 这个模块，不会替我们读 zip 里的 .env；不在这里读，
# 那个文件就是摆设（实测：import 后 ANTHROPIC_API_KEY 仍是 None，mode=heuristic）。
# load_env_file 幂等，且**已存在的真实环境变量优先**——平台「模型管理」注入的值
# 不会被仓里的 .env 覆盖。
from bugfix_contracts.env import load_env_file

load_env_file()

from bugfix_platform.workflow.langgraph_app import graph  # noqa: E402

__all__ = ["graph", "build_graph", "main"]


def build_graph():
    """返回已编译的父级 StateGraph（Agent-2 → Agent-3）。"""
    return graph


def main() -> int:
    """平台若无 ``graph`` 属性时回退到 ``main()``；这里不做实际工作。"""
    print("bugfix-agent: use `graph` / `build_graph()`; run via LangGraph Server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
