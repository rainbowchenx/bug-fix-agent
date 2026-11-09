"""平台入口：zip 根级 ``graph.py``。

公司 agent 平台要求 zip 根目录存在 ``graph.py``，并暴露
``build_graph()`` / ``graph`` / ``main()`` 三者之一。这里三个都给。

真正的图定义在 ``bugfix_platform/workflow/langgraph_app.py``，此处只做转发——
不要在两边各写一份 StateGraph，否则漂移后平台和本地跑的不是同一张图。

注意：**不要**在这里挂 ``InMemorySaver``。持久化由平台 Server 负责。
"""

from __future__ import annotations

from bugfix_platform.workflow.langgraph_app import graph

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
