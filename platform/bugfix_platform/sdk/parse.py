from __future__ import annotations

import json
import re
from typing import Any, Optional

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


def parse_json_payload(raw: Any) -> Optional[dict[str, Any]]:
    """Extract a JSON object from SDK structured_output, raw dict, or fenced text."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE.search(text)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None
