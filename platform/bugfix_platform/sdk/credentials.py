"""Anthropic 凭据判定：API key 与 bearer token 同等对待。

Agent-2/3 的 ``sdk`` 模式与「有没有凭据」绑在一起。之前只看
``ANTHROPIC_API_KEY``，而 ``.env.example`` 自己推荐的网关配法
（DeepSeek 等 Anthropic 兼容网关）用的是 ``ANTHROPIC_AUTH_TOKEN`` ——
那种部署会静默退化成 heuristic，产物里还写着「heuristic mode」。

判定口径：非空即算。空串（``.env`` 里留 ``KEY=`` 的占位）不算。
"""

from __future__ import annotations

import os

__all__ = ["CREDENTIAL_ENV_NAMES", "credentials_env_name", "has_credentials"]

# 顺序即优先级：只有用来写诊断信息，不影响判定结果。
CREDENTIAL_ENV_NAMES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def credentials_env_name() -> str | None:
    """返回第一个非空凭据变量名；都没有则 ``None``。"""
    for name in CREDENTIAL_ENV_NAMES:
        if (os.environ.get(name) or "").strip():
            return name
    return None


def has_credentials() -> bool:
    """有没有可用于 SDK 的凭据。"""
    return credentials_env_name() is not None
