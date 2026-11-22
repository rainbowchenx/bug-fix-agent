"""Read the cartography response envelope and SDK tool observations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def find_business_envelope(
    *,
    structured: Any,
    texts: list[str],
) -> tuple[Optional[dict[str, Any]], str]:
    """选业务信封：空对象/工具 JSON 不能挡住带调查字段的对象。"""
    scored: list[tuple[int, str, dict[str, Any]]] = []
    if isinstance(structured, dict) and structured:
        scored.append((_envelope_score(structured), "structured_output", structured))
    elif isinstance(structured, str):
        for ordinal, obj in enumerate(_extract_objects(structured)):
            scored.append((_envelope_score(obj), f"structured_output.objects[{ordinal}]", obj))
    for index, text in enumerate(texts):
        for ordinal, obj in enumerate(_extract_objects(text)):
            scored.append((_envelope_score(obj), f"texts[{index}].objects[{ordinal}]", obj))
    business = [row for row in scored if row[0] > 0]
    if not business:
        return None, "none"
    business.sort(key=lambda row: row[0], reverse=True)
    _, ref, obj = business[0]
    return obj, ref


def _envelope_score(obj: dict[str, Any]) -> int:
    if not isinstance(obj, dict) or not obj:
        return 0
    if obj.get("type") == "tool_result" or set(obj) <= {"ok", "content", "type"}:
        return 0
    score = 0
    matches = obj.get("defectCodeMatches")
    if isinstance(matches, list):
        score += 10 + sum(1 for item in matches if isinstance(item, dict) and item.get("defectId"))
    elif "defectCodeMatches" in obj:
        score += 1
    for key in ("architecture", "techStack", "conventions", "boundSkills", "partial"):
        if key in obj:
            score += 2
    return score


def _extract_objects(text: str) -> list[dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return []
    found: list[dict[str, Any]] = []
    raw = text.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            found.append(data)
            return found
    except json.JSONDecodeError:
        pass
    start = 0
    n = len(raw)
    while start < n:
        i = raw.find("{", start)
        if i < 0:
            break
        chunk, nxt = _scan_json_object(raw, i)
        if chunk is None:
            start = i + 1
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            start = i + 1
            continue
        if isinstance(data, dict):
            found.append(data)
        start = nxt
    return found


def _scan_json_object(text: str, start: int) -> tuple[Optional[str], int]:
    """扫描一个 JSON 对象；字符串内花括号不计深度。失败时前进一格。"""
    if start >= len(text) or text[start] != "{":
        return None, start + 1
    depth = 0
    in_str = False
    escape = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
        i += 1
    return None, start + 1


def apply_tool_observation(
    pending: dict[str, str],
    observed: list[str],
    block: Any,
    work_dir: str,
) -> None:
    """仅在成功 ToolResult 后记录规范化观察范围。"""
    name = getattr(block, "name", None) or (block.get("name") if isinstance(block, dict) else None)
    params = getattr(block, "input", None) or (block.get("input") if isinstance(block, dict) else {}) or {}
    tool_id = getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else None)
    use_id = getattr(block, "tool_use_id", None) or (block.get("tool_use_id") if isinstance(block, dict) else None)
    if name in {"Read", "Grep", "Glob"} and tool_id:
        ref = params.get("file_path") or params.get("path")
        if isinstance(ref, str) and ref.strip():
            pending[str(tool_id)] = repo_relative_path(work_dir, ref) or ""
        return
    if not use_id:
        return
    key = str(use_id)
    if key not in pending:
        return
    is_error = bool(getattr(block, "is_error", False) or (block.get("is_error") if isinstance(block, dict) else False))
    content = getattr(block, "content", None) if not isinstance(block, dict) else block.get("content")
    rel = pending.pop(key)
    if not is_error and content and rel:
        observed.append(rel)


def repo_relative_path(work_dir: str, raw: str) -> str | None:
    """返回仓内相对路径；越界路径返回 None，不得折叠成仓内同名路径。"""
    root = Path(work_dir).resolve()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        rel = path.resolve().relative_to(root)
    except ValueError:
        return None
    return normalize_observed_path(str(rel))


def normalize_observed_path(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")
