"""LangGraph Server / CLI entrypoint.

``langgraph.json`` points here so `langgraph dev` / Platform can load the
compiled three-agent parent graph without a custom checkpointer (the server
supplies persistence).
"""

from __future__ import annotations

from bugfix_agent.workflow.graph import create_three_agent_graph

# Server-managed checkpointer — do not attach InMemorySaver here.
graph = create_three_agent_graph()
