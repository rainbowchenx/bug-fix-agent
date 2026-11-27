"""Bound Agent-3 source exploration and measure the SDK traffic per ticket."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bugfix_contracts.analysis_report import AnalysisUsage
from bugfix_contracts.repair import AnalysisReadRange, AnalysisSearchRecord, AnalysisToolHistory
from bugfix_platform.sdk.codegraph import CODEGRAPH_MCP_TOOLS
from bugfix_platform.sdk.trace import usage_totals
from bugfix_platform.workspace_fingerprint import workspace_digest

_FALLBACK_TOOLS = {"Grep", "Glob"}
_MAX_READ_LINES = 80
_GRAPH_TOOLS = frozenset(CODEGRAPH_MCP_TOOLS)
_SEARCH_TOOLS = _FALLBACK_TOOLS | _GRAPH_TOOLS
_TRACKED = _SEARCH_TOOLS | {"Read"}


class AnalysisTools:
    def __init__(
        self, work_dir: str, *, graph_ready: bool, full_read_paths: list[str], source_digest: str | None = None,
    ) -> None:
        self.work_dir = Path(work_dir).resolve()
        self.full_read_paths = {self.resolve(path) for path in full_read_paths}
        self.graph_ready = graph_ready
        self.source_digest = source_digest
        self.usage = AnalysisUsage()
        self.read_paths: set[str] = set()
        self.begin_query()

    def resolve(self, path: str) -> Path:
        return (self.work_dir / path).resolve()

    def begin_query(self, resume: str | None = None, history: AnalysisToolHistory | None = None) -> None:
        self.graph_available = self.graph_ready
        self.graph_tried = False
        self._resume = resume
        self._history = history
        self._queries: set[str] = set()
        self._completed_queries: dict[str, AnalysisSearchRecord] = {}
        self._scope_digests: dict[Path, str | None] = {}
        self._read_ranges: dict[tuple[Path, int, int], str | None] = {}
        self._requests: dict[str, tuple[str, dict[str, Any]]] = {}
        self._blocked: set[str] = set()
        self._results: dict[str, Any] = {}

    def _restore(self, session_id: str | None) -> None:
        history, self._history = self._history, None
        if not history or not session_id or session_id != self._resume or history.sessionId != session_id:
            return
        if Path(history.workDir) != self.work_dir:
            return
        for item in history.reads:
            path = self.resolve(item.path)
            if path.is_relative_to(self.work_dir):
                self._read_ranges[path, item.offset, item.limit] = item.digest
        if self.source_digest and history.sourceDigest == self.source_digest:
            self.graph_tried = history.graphTried
        for record in history.queries:
            if record.digest == self._scope_digest(self.resolve(record.scope)):
                self._queries.add(record.key)
                self._completed_queries[record.key] = record
                self.graph_tried |= record.codeGraph

    def history(self, session_id: str) -> AnalysisToolHistory:
        return AnalysisToolHistory(
            sessionId=session_id, workDir=str(self.work_dir), sourceDigest=self.source_digest,
            reads=[
                AnalysisReadRange(path=path.relative_to(self.work_dir).as_posix(), digest=digest, offset=offset, limit=limit)
                for (path, offset, limit), digest in self._read_ranges.items()
                if digest and path.is_relative_to(self.work_dir)
            ],
            queries=list(self._completed_queries.values()), graphTried=self.graph_tried,
        )

    def _scope_digest(self, path: Path) -> str | None:
        if not path.is_relative_to(self.work_dir):
            return None
        if path == self.work_dir:
            return self.source_digest
        if path not in self._scope_digests:
            try:
                self._scope_digests[path] = workspace_digest(path) if path.is_dir() else _file_digest(path)
            except OSError:
                return None
        return self._scope_digests[path]

    def _record_search(self, tool: str, params: dict[str, Any]) -> None:
        graph = tool in _GRAPH_TOOLS
        path = self.resolve(str(params.get("projectPath" if graph else "path") or "."))
        if digest := self._scope_digest(path):
            key = _query_digest(tool, params)
            self._completed_queries[key] = AnalysisSearchRecord(
                key=key, scope=path.relative_to(self.work_dir).as_posix(), digest=digest, codeGraph=graph,
            )

    def hooks(self, *, output_only: bool) -> list[Any]:
        try:
            from claude_agent_sdk import HookMatcher
        except ImportError:
            return []
        from bugfix_platform.sdk.claude_cli import hook_on_failure_supported

        async def before_tool(payload: dict[str, Any], tool_id: str | None, _context: Any) -> dict[str, Any]:
            tool = payload.get("tool_name")
            tool_id = tool_id or payload.get("tool_use_id")
            decision = self.before_tool(payload, output_only=output_only, tool_id=tool_id)
            # The SDK can report permission denials without a matching assistant frame.
            if tool_id and tool in _TRACKED:
                params = decision.get("hookSpecificOutput", {}).get("updatedInput", payload.get("tool_input") or {})
                self._requests[tool_id] = (tool, params)
                if decision.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                    self._blocked.add(tool_id)
            return decision

        matcher = ".*" if output_only else "Read|Grep|Glob|" + "|".join(CODEGRAPH_MCP_TOOLS)
        kwargs = {"on_failure": "block"} if hook_on_failure_supported() else {}
        return [HookMatcher(matcher=matcher, hooks=[before_tool], **kwargs)]

    def before_tool(self, payload: dict[str, Any], *, output_only: bool = False, tool_id: str | None = None) -> dict[str, Any]:
        tool = payload.get("tool_name")
        params = payload.get("tool_input") or {}
        if output_only:
            return _deny("Return the structured analysis using evidence already collected.")
        if tool == "Read" and isinstance(path := params.get("file_path"), str):
            resolved = self.resolve(path)
            if resolved in self.full_read_paths:
                return {}
            start, limit = _read_window(params)
            key = (resolved, start, limit)
            if key in self._read_ranges:
                digest = self._read_ranges[key]
                if digest is None or digest == _file_digest(resolved):
                    if tool_id not in self._blocked:
                        self.usage.duplicateReadsBlocked += 1
                    return _deny("This source range was already returned. Use it or request a different range.")
                del self._read_ranges[key]
            if params.get("offset") != start or params.get("limit") != limit:
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "updatedInput": {**params, "offset": start, "limit": limit},
                }}
        if tool in _SEARCH_TOOLS:
            if tool in _FALLBACK_TOOLS:
                if self.graph_available and not self.graph_tried:
                    return _deny("Use CodeGraph first and inspect its result before falling back to Grep or Glob.")
                if not params.get("path"):
                    return _deny("Set path to the relevant repository or module for fallback search.")
            key = _query_digest(tool, params)
            if key in self._queries:
                return _deny("This search already ran in this session. Use its result or narrow the query.")
            self._queries.add(key)
        return {}

    def observe(self, message: Any) -> None:
        if getattr(message, "subtype", None) == "init":
            data = getattr(message, "data", None) or {}
            self._restore(data.get("session_id"))
            servers = data.get("mcp_servers")
            if isinstance(servers, list):
                self.graph_available = self.graph_ready and any(
                    server.get("name") == "codegraph" and server.get("status") == "connected"
                    for server in servers if isinstance(server, dict)
                )
        content = getattr(message, "content", None)
        for block in content if isinstance(content, list) else ():
            self._observe_block(block)

    def _observe_block(self, block: Any) -> None:
        tool = getattr(block, "name", None)
        if tool in _TRACKED:
            self._requests.setdefault(block.id, (tool, block.input or {}))
            return
        tool_id = getattr(block, "tool_use_id", None)
        if tool_id not in self._requests or tool_id in self._blocked or tool_id in self._results:
            return
        self._results[tool_id] = block
        tool, params = self._requests[tool_id]
        if tool in _GRAPH_TOOLS:
            self.graph_tried = True
        if getattr(block, "is_error", False):
            return
        if tool in _SEARCH_TOOLS:
            self._record_search(tool, params)
            return
        if not getattr(block, "content", None) or not params.get("file_path"):
            return
        path = self.resolve(params["file_path"])
        if path not in self.full_read_paths:
            start, limit = _read_window(params)
            self._read_ranges[path, start, limit] = _file_digest(path) if path.is_relative_to(self.work_dir) else None

    def finish_query(self) -> None:
        for tool_id, (tool, params) in self._requests.items():
            prefix = "read" if tool == "Read" else "codeGraph" if tool in _GRAPH_TOOLS else "grepGlob"
            self._increment(prefix + "Requests")
            if tool_id in self._blocked:
                self._increment(prefix + "Blocked")
                continue
            block = self._results.get(tool_id)
            if block is None:
                continue
            self._increment(prefix + "Calls")
            if tool == "Read" and not getattr(block, "is_error", False) and params.get("file_path"):
                self._measure_read(params["file_path"], getattr(block, "content", None))

    def _increment(self, name: str) -> None:
        setattr(self.usage, name, getattr(self.usage, name) + 1)

    def _measure_read(self, path: str, content: Any) -> None:
        if not content:
            return
        self.read_paths.add(str(self.resolve(path)))
        text = content if isinstance(content, str) else "\n".join(
            item["text"] for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
        self.usage.readResultLines += len(text.splitlines())
        self.usage.readResultBytes += len(text.encode("utf-8"))

    def observe_result(self, message: Any) -> None:
        for denial in getattr(message, "permission_denials", None) or []:
            if isinstance(denial, dict) and (tool_id := denial.get("tool_use_id")):
                self._blocked.add(tool_id)
                tool = denial.get("tool_name")
                if tool in _TRACKED:
                    self._requests.setdefault(tool_id, (tool, denial.get("tool_input") or {}))
        self.usage.sdkResults += 1
        if isinstance(turns := getattr(message, "num_turns", None), int) and turns >= 0:
            self.usage.turnReports += 1
            self.usage.turns += turns
        totals = usage_totals(getattr(message, "usage", None))
        if totals:
            self.usage.usageReports += 1
        self.usage.inputTokens += totals.get("input", 0)
        self.usage.outputTokens += totals.get("output", 0)
        self.usage.cacheReadTokens += totals.get("cache_read", 0)
        self.usage.cacheWriteTokens += totals.get("cache_write", 0)


def _read_window(params: dict[str, Any]) -> tuple[int, int]:
    offset, limit = params.get("offset"), params.get("limit")
    offset = offset if type(offset) is int and offset > 0 else 1
    limit = limit if type(limit) is int and limit > 0 else _MAX_READ_LINES
    return offset, min(limit, _MAX_READ_LINES)


def _query_digest(tool: str, params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([tool, params], sort_keys=True).encode()).hexdigest()


def _file_digest(path: Path) -> str | None:
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except OSError:
        return None


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}
