"""Loosely coupled agents — communicate only via contracts."""

from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.agents.analyst import run_analyst

__all__ = ["run_cartographer", "run_analyst"]
