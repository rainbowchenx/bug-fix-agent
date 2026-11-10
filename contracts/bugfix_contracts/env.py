"""``.env`` 读取：零依赖，且**永不覆盖**已存在的真实环境变量。

README 让用户 ``cp .env.example .env``，但在此之前没有任何代码读这个文件——
写了等于没写。这里补上最小实现，两个产品共用：

- 只认 KEY=VALUE，支持 ``export KEY=value``、单双引号包裹、``#`` 注释、空行
- 不做变量展开、不做类型转换（``BUGFIX_ANALYZE_LIMIT=`` 保持空串）
- **已有环境变量优先**：平台上注入的值不会被仓里的 .env 改掉，凭据仍然只走环境变量
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["load_env_file", "ENV_FILE_VAR"]

# 显式指定用哪个文件（相对路径按 CWD 解析）；也方便测试与多环境切换。
ENV_FILE_VAR = "BUGFIX_ENV_FILE"


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").replace(".", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        out[key] = value
    return out


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """把 ``.env`` 灌进 ``os.environ``，返回实际生效的键值。

    默认只看 CWD 下的 ``.env``（或 ``BUGFIX_ENV_FILE`` 指向的文件）。
    文件不存在就是空操作——不要为了"没配 .env"报错。
    """
    target = path or os.environ.get(ENV_FILE_VAR) or ".env"
    candidate = Path(target).expanduser()
    try:
        if not candidate.is_file():
            return {}
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return {}

    applied: dict[str, str] = {}
    for key, value in _parse(text).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied
