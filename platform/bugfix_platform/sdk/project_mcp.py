"""Explicit, per-run repository MCP selection for Agent 3."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from bugfix_contracts.code_knowledge import RepoRoot
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS, CodeGraphStatus

_TOOL_NAME = re.compile(r"mcp__([A-Za-z0-9_-]+?)__[A-Za-z0-9_-]+")


class ProjectMcpConfigError(ValueError):
    """An explicitly approved repository MCP cannot be resolved."""


@dataclass(frozen=True)
class ProjectMcp:
    tools: tuple[str, ...] = ()
    servers: dict[str, tuple[Path, dict[str, Any]]] = field(default_factory=dict)

    def sdk_options(self, work_dir: str, codegraph: CodeGraphStatus | None = None) -> dict[str, Any]:
        options = (codegraph or CodeGraphStatus(ready=False)).mcp_option_kwargs(work_dir)
        if not self.tools:
            return options

        from claude_agent_sdk import HookMatcher

        builtin = options["mcp_servers"] if isinstance(options["mcp_servers"], dict) else {}
        servers = {name: _server_options(Path(work_dir) / repo, config)
                   for name, (repo, config) in self.servers.items()}
        permitted = frozenset(self.tools) | (frozenset(CODEGRAPH_MCP_TOOLS) if builtin else frozenset())

        async def check_tool(hook_input: Any, _tool_use_id: str | None, _context: Any) -> dict[str, Any]:
            if hook_input.get("tool_name") in permitted:
                return {}
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "MCP tool is outside this Agent 3 run's allowlist",
                },
            }

        options["mcp_servers"] = {**servers, **builtin}
        options["hooks"] = {"PreToolUse": [HookMatcher(
            matcher="mcp__.*", hooks=[check_tool], on_failure="block",
        )]}
        return options


def load_project_mcp(
    work_dir: str | Path, repo_roots: Sequence[RepoRoot], tools: Sequence[str] = (),
) -> ProjectMcp:
    tools = tuple(dict.fromkeys(tools))
    if not tools:
        return ProjectMcp()

    requested: set[str] = set()
    for tool in tools:
        match = _TOOL_NAME.fullmatch(tool)
        if not match or match[1].lower() == "codegraph":
            raise ProjectMcpConfigError("Agent 3 business MCP tools must use mcp__<server>__<tool>; codegraph is reserved")
        requested.add(match[1])

    root = Path(work_dir).resolve()
    roots = dict.fromkeys([root, *((root / repo.path).resolve() for repo in repo_roots)])
    servers: dict[str, tuple[Path, dict[str, Any]]] = {}
    for repo in roots:
        if not repo.is_relative_to(root):
            raise ProjectMcpConfigError("Agent 3 business MCP repository must be inside workDir")
        source = repo / ".mcp.json"
        if not source.is_file():
            continue
        if not source.resolve().is_relative_to(repo):
            raise ProjectMcpConfigError(f"Agent 3 MCP configuration points outside its repository: {source}")
        try:
            document = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as err:
            raise ProjectMcpConfigError(f"Cannot read Agent 3 MCP configuration: {source}") from err
        entries = document.get("mcpServers") if isinstance(document, dict) else None
        if not isinstance(entries, dict):
            raise ProjectMcpConfigError(f"Expected an mcpServers object in {source}")
        for name in requested.intersection(entries):
            if name in servers:
                raise ProjectMcpConfigError(f"Agent 3 MCP server {name!r} is defined in more than one repository")
            config = entries[name]
            kind = config.get("type", "stdio") if isinstance(config, dict) else None
            required_key = {"stdio": "command", "http": "url", "sse": "url", "streamable-http": "url"}.get(kind) if isinstance(kind, str) else None
            if not required_key or not isinstance(config.get(required_key), str) or not config[required_key].strip():
                raise ProjectMcpConfigError(f"Invalid or unsupported Agent 3 MCP server {name!r} in {source}")
            if kind == "stdio" and (not isinstance(args := config.get("args", []), list)
                                     or not all(isinstance(arg, str) for arg in args)):
                raise ProjectMcpConfigError(f"Expected string arguments for Agent 3 MCP server {name!r} in {source}")
            servers[name] = (repo.relative_to(root), config)

    if missing := requested.difference(servers):
        raise ProjectMcpConfigError(f"Agent 3 MCP servers not found in repository .mcp.json: {', '.join(sorted(missing))}")
    return ProjectMcp(tools=tools, servers=servers)


def _server_options(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    if config.get("type", "stdio") != "stdio":
        return dict(config)
    launcher = Path(__file__).with_name("_project_mcp_stdio.py")
    command = [config["command"], *config.get("args", [])]
    args = ["-I", str(launcher), str(repo.resolve()), *command]
    if os.name == "nt":
        from bugfix_platform.sdk._codegraph_windows import process_creation_time

        args[2:2] = [str(os.getpid()), str(process_creation_time())]
    return {**config, "type": "stdio", "command": sys._base_executable or sys.executable, "args": args}
