"""LangGraph Server / CLI 入口。

``langgraph.json`` 把图 id ``three_agent`` 映射到本模块的 ``graph``，供
``langgraph dev`` / Platform 加载父级 StateGraph。

此处**不要**挂 ``InMemorySaver``：持久化由 Server 负责。本地 CLI/HTTP 的
可恢复执行走 ``run_three_agent_workflow(thread_id=...)``。
"""

from __future__ import annotations

from bugfix_agent.workflow.graph import create_three_agent_graph

# 导出符号名必须与 langgraph.json 中的 "...:graph" 一致。
graph = create_three_agent_graph()
