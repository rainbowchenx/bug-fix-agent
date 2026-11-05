"""LangGraph Server / CLI entrypoint.

``langgraph.json`` maps graph id ``three_agent`` → ``graph`` in this module so
``langgraph dev`` / Platform can load the parent StateGraph.

Do **not** attach ``InMemorySaver`` here: the server owns persistence. Local
CLI/HTTP durability goes through ``run_three_agent_workflow(thread_id=...)``
instead.
"""

from __future__ import annotations

from bugfix_agent.workflow.graph import create_three_agent_graph

# Exported symbol name must match langgraph.json ("...:graph").
graph = create_three_agent_graph()
