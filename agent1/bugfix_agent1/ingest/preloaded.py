from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from bugfix_contracts.defect_batch import RawDefect, RawDefectsFile
from bugfix_agent1.ingest.csv_source import load_platform_csv


Source = Union[str, Path, dict[str, Any], list[Any]]


def load_preloaded(source: Source) -> list[RawDefect]:
    """把预置载荷归一成 ``RawDefect`` 列表（Ingest 的 ``preloaded`` 实现）。

    后续蒸馏 / 筛选 / 分簇只读本函数产物，不再回查平台。

    Args:
        source: 文件路径（``.csv`` / ``raw-defects`` JSON / 缺陷列表 JSON）、
            内存 dict（含 ``defects`` 的文件对象，或单条平台/canonical 行）、
            或缺陷 dict / ``RawDefect`` 列表。

    Returns:
        归一后的 ``RawDefect`` 列表。

    Raises:
        TypeError: 列表项不是 dict / ``RawDefect``。
        ValidationError: 条目无法映射为 ``RawDefect``。
    """
    if isinstance(source, list):
        return [_coerce_item(x) for x in source]
    if isinstance(source, dict):
        # Already-normalized file OR a single platform row
        if "defects" in source:
            parsed = RawDefectsFile.model_validate(source)
            return parsed.defects
        mapped = _coerce_item(source)
        return [mapped]

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_platform_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [_coerce_item(x) for x in data]
    if isinstance(data, dict) and "defects" in data:
        return RawDefectsFile.model_validate(data).defects
    return [_coerce_item(data)]


def _coerce_item(item: Any) -> RawDefect:
    """把单条记录收成 ``RawDefect``。

    已是 ``RawDefect`` 或含 ``title`` + ``defectId`` 的 canonical dict 则直接
    校验；否则走 ``row_to_raw_dict`` 做平台列名映射。

    Args:
        item: ``RawDefect``、canonical dict 或平台行 dict。

    Returns:
        校验通过的 ``RawDefect``。

    Raises:
        TypeError: ``item`` 不是 dict / ``RawDefect``。
        ValidationError: 映射后仍不满足契约。
    """
    if isinstance(item, RawDefect):
        return item
    if not isinstance(item, dict):
        raise TypeError(f"defect item must be dict, got {type(item)}")
    # Fast path: already canonical
    if "title" in item and "defectId" in item:
        return RawDefect.model_validate(item)
    from bugfix_agent1.ingest.field_map import row_to_raw_dict

    mapped = row_to_raw_dict(item)
    if not mapped:
        # fall through to pydantic for a clear error
        return RawDefect.model_validate(item)
    return RawDefect.model_validate(mapped)
