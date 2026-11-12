"""Map platform / Excel column names onto RawDefect fields.

Platform CSV exports (缺陷拉取) use English camelCase keys with a few
idiosyncrasies (`describle`, `flowStatusName`, `severityName`, …).
Chinese Excel exports use 缺陷ID / 缺陷标题 / ….
"""

from __future__ import annotations

from typing import Any, Mapping

# Canonical RawDefect field → accepted source column names (first hit wins).
FIELD_ALIASES: dict[str, list[str]] = {
    # `缺陷单号` is the primary key on the Chinese web export. Missing it made
    # every row unmappable, which the funnel reports as a cheerful 0-ticket run.
    # `单号` is the headline on 缺陷拉取 (iRDMS) CSV exports; without it every
    # row is unmappable and the funnel reports a cheerful 0-ticket run.
    "defectId": [
        "defectId",
        "缺陷单号",
        "单号",
        "缺陷ID",
        "缺陷编号",
        "ID",
        "id",
    ],
    "title": ["defectTitle", "缺陷标题", "标题", "title"],
    # Platform typo `describle` is intentional and must stay.
    "description": ["describle", "defectDescribe", "缺陷描述", "描述", "description"],
    "status": ["defectStatus", "缺陷状态", "状态", "status"],
    "flowStatus": ["flowStatusName", "flowStatus", "流程状态"],
    # `测试模块` is filled at creation, `所属模块` at close. Prefer the former:
    # one export ships both, with `所属模块` blank on every open ticket.
    # `模块` is what the iRDMS export calls it (comma-joined path, e.g.
    # `结构,校正工具,接收卡`).
    "testModule": ["testModule", "测试模块", "所属模块", "模块"],
    "fieldType": ["defectType", "类型", "缺陷类型", "type", "fieldType"],
    "severity": ["severityName", "severity", "严重级别", "级别"],
    "createdAt": ["createDate", "createdAt", "创建时间"],
    "duplicateOf": [
        "duplicateOf",
        "关联重复缺陷编号",
        "关联缺陷ID",
        "relateDefectId",
    ],
}

# Extra columns parked into RawDefect.metadata (not screening inputs).
# Note: `BatchTicket` has no metadata field, so these are dropped before the
# artifact is written -- they only survive on the in-memory RawDefect. Kept
# English-only to match what the platform's English export actually ships.
METADATA_KEYS = [
    "flowInstId",
    "detectingActivityI18n",
    "assignee",
    "discoveredBy",
    "discoveredByName",
    "solvedBy",
    "devName",
    "softName",
    "revision",
    "testRequestId",
]


def _cell(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def pick_field(row: Mapping[str, Any], aliases: list[str]) -> str:
    for name in aliases:
        if name in row:
            val = _cell(row.get(name))
            if val:
                return val
    # case-insensitive fallback
    lower_map = {str(k).lower(): k for k in row.keys()}
    for name in aliases:
        key = lower_map.get(name.lower())
        if key is not None:
            val = _cell(row.get(key))
            if val:
                return val
    return ""


def row_to_raw_dict(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """把一行平台 / Excel 记录映射为 ``RawDefect`` 形状的 dict。

    Args:
        row: 原始列名到单元格的映射（英文导出或中文表头均可）。

    Returns:
        可供 ``RawDefect.model_validate`` 的 dict；缺 ``defectId`` 或
        ``title`` 时返回 ``None``（调用方应跳过该行）。
    """
    defect_id = pick_field(row, FIELD_ALIASES["defectId"])
    title = pick_field(row, FIELD_ALIASES["title"])
    if not defect_id or not title:
        return None

    out: dict[str, Any] = {
        "defectId": defect_id,
        "title": title,
        "description": pick_field(row, FIELD_ALIASES["description"]),
    }
    for key in (
        "status",
        "flowStatus",
        "testModule",
        "fieldType",
        "severity",
        "createdAt",
        "duplicateOf",
    ):
        val = pick_field(row, FIELD_ALIASES[key])
        if val:
            out[key] = val

    meta: dict[str, Any] = {}
    for mk in METADATA_KEYS:
        if mk in row:
            val = _cell(row.get(mk))
            if val and val != "********":
                meta[mk] = val
    if meta:
        out["metadata"] = meta
    return out
