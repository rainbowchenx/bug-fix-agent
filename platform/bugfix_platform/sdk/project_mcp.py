"""Per-run repository MCP selection and opt-in Claude Code integrations."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Collection, Sequence

from bugfix_contracts.code_knowledge import RepoRoot
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS, CodeGraphStatus

_TOOL_NAME = re.compile(r"mcp__([A-Za-z0-9_-]+?)__[A-Za-z0-9_-]+")


class ProjectMcpConfigError(ValueError):
    """An explicitly approved repository MCP cannot be resolved."""


@dataclass(frozen=True)
class ProjectMcp:
    tools: tuple[str, ...] = ()
    servers: dict[str, tuple[Path, dict[str, Any]]] = field(default_factory=dict)
    full_access: bool = False
    repo_dirs: tuple[Path, ...] = ()
    plugin_dirs: tuple[Path, ...] = ()

    def allowed_tools(self) -> tuple[str, ...]:
        if self.full_access:
            return ("Skill", "Agent", "ToolSearch", *(f"mcp__{name}__*" for name in self.servers))
        return self.tools

    def sdk_options(self, work_dir: str, codegraph: CodeGraphStatus | None = None) -> dict[str, Any]:
        options = (codegraph or CodeGraphStatus(ready=False)).mcp_option_kwargs(work_dir)
        if not self.tools and not self.full_access:
            return options

        builtin = options["mcp_servers"] if isinstance(options["mcp_servers"], dict) else {}
        servers = {name: _server_options(Path(work_dir) / repo, config)
                   for name, (repo, config) in self.servers.items()}
        options["mcp_servers"] = {**servers, **builtin}
        if self.full_access:
            options.update(
                strict_mcp_config=False,
                setting_sources=["user", "project", "local"],
                settings=json.dumps({"enableAllProjectMcpServers": True}),
                add_dirs=[str(Path(work_dir) / repo) for repo in self.repo_dirs],
                permission_mode="default",
                can_use_tool=_approve_integration_tool,
            )
            if self.plugin_dirs:
                options["plugins"] = [{"type": "local", "path": str(path)} for path in self.plugin_dirs]
            return options

        from claude_agent_sdk import HookMatcher

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

        # 老版本 CLI 不认 onFailure，传了会让 initialize 直接失败。
        from bugfix_platform.sdk.claude_cli import hook_on_failure_supported

        matcher_kwargs: dict[str, Any] = {"matcher": "mcp__.*", "hooks": [check_tool]}
        if hook_on_failure_supported():
            matcher_kwargs["on_failure"] = "block"
        options["hooks"] = {"PreToolUse": [HookMatcher(**matcher_kwargs)]}
        return options


async def _approve_integration_tool(tool_name: str, _tool_input: Any, _context: Any) -> Any:
    from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

    # Plugin and user MCP names are discovered by the native CLI at startup.
    if tool_name.startswith("mcp__") or tool_name in {"Skill", "Agent", "ToolSearch"}:
        return PermissionResultAllow()
    return PermissionResultDeny(message="Use the tools available for this Agent phase")


def load_project_mcp(
    work_dir: str | Path, repo_roots: Sequence[RepoRoot], tools: Sequence[str] = (),
    *, full_access: bool = False,
) -> ProjectMcp:
    tools = tuple(dict.fromkeys(tools))
    if not tools and not full_access:
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
    repo_dirs: list[Path] = []
    for repo in roots:
        if not repo.is_relative_to(root):
            raise ProjectMcpConfigError("Agent 3 business MCP repository must be inside workDir")
        relative = repo.relative_to(root)
        if repo != root:
            repo_dirs.append(relative)
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
        for name in entries if full_access else requested.intersection(entries):
            # 内置 codegraph 由 codegraph.py 挂载并独占 .codegraph/ 的 writer lock。
            # 业务仓 .mcp.json 里再配一份只会抢锁失败（"Connection closed"），
            # 而 init 列表里仍显示 connected，模型要浪费两轮才发现它是坏的。
            if full_access and name.lower() == "codegraph":
                continue
            if not full_access and name in servers:
                raise ProjectMcpConfigError(f"Agent 3 MCP server {name!r} is defined in more than one repository")
            config = entries[name]
            kind = config.get("type", "stdio") if isinstance(config, dict) else None
            required_key = {"stdio": "command", "http": "url", "sse": "url", "streamable-http": "url"}.get(kind) if isinstance(kind, str) else None
            if not required_key or not isinstance(config.get(required_key), str) or not config[required_key].strip():
                raise ProjectMcpConfigError(f"Invalid or unsupported Agent 3 MCP server {name!r} in {source}")
            if kind == "stdio" and (not isinstance(args := config.get("args", []), list)
                                     or not all(isinstance(arg, str) for arg in args)):
                raise ProjectMcpConfigError(f"Expected string arguments for Agent 3 MCP server {name!r} in {source}")
            if full_access and name in servers:
                suffix = sha256(relative.as_posix().encode()).hexdigest()[:8]
                alias = f"{name}-{suffix}"
                while alias in servers or alias in entries:
                    alias += "-mcp"
                name = alias
            servers[name] = (relative, config)

    if not full_access and (missing := requested.difference(servers)):
        raise ProjectMcpConfigError(f"Agent 3 MCP servers not found in repository .mcp.json: {', '.join(sorted(missing))}")
    return ProjectMcp(
        tools=tools, servers=servers, full_access=full_access, repo_dirs=tuple(repo_dirs),
        plugin_dirs=_installed_plugins(roots) if full_access else (),
    )


def _installed_plugins(roots: Collection[Path]) -> tuple[Path, ...]:
    """Resolve installed plugin directories for the SDK, honoring install scope."""
    default_config = Path.home() / ".claude"
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or default_config).expanduser()
    registry = config / "plugins" / "installed_plugins.json"
    if not registry.is_file():
        return ()
    try:
        data = json.loads(registry.read_text(encoding="utf-8-sig"))
        plugins = data["plugins"]
        if not isinstance(plugins, dict):
            raise ValueError("plugins must be an object")
    except (OSError, TypeError, KeyError, ValueError) as err:
        raise ProjectMcpConfigError(f"Cannot read Claude Code plugins registry: {registry}") from err
    scope_rank = {"user": 0, "project": 1, "local": 2}
    directories: dict[Path, None] = {}
    for records in plugins.values():
        if isinstance(records, dict):  # Legacy registry uses a single record per plugin.
            records = [records]
        if not isinstance(records, list):
            continue
        candidates = []
        for record in records:
            if not isinstance(record, dict) or not isinstance(path := record.get("installPath"), str) or not path:
                continue
            scope = record.get("scope", "user")
            if scope in ("project", "local"):
                project = record.get("projectPath")
                if not isinstance(project, str) or Path(project).expanduser().resolve() not in roots:
                    continue
            directory = Path(path).expanduser()
            if directory.is_dir():
                candidates.append((scope_rank.get(scope, 0), directory.resolve()))
        if candidates:
            _, directory = max(candidates, key=lambda item: item[0])
            directories[directory] = None
    return tuple(directories)


def _server_options(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    kind = config.get("type", "stdio")
    if kind == "streamable-http":
        return {**config, "type": "http"}
    if kind != "stdio":
        return dict(config)
    launcher = Path(__file__).with_name("_project_mcp_stdio.py")
    command = [config["command"], *config.get("args", [])]
    args = ["-I", str(launcher), str(repo.resolve()), *command]
    if os.name == "nt":
        from bugfix_platform.sdk._codegraph_windows import process_creation_time

        args[2:2] = [str(os.getpid()), str(process_creation_time())]
    return {**config, "type": "stdio", "command": sys._base_executable or sys.executable, "args": args}
