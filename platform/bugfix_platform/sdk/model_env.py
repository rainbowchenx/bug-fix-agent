"""模型配置：把平台注入的变量映射成 Claude Agent SDK 认的 ``ANTHROPIC_*``。

## 为什么需要这一层

Nexas OS 的 LangGraph 执行路径（``dist-electron/main.js`` 的 ``injectModelConfig``）
往子进程里注入的是 **OpenAI 命名**的三个变量：

    OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL

而 Claude Agent SDK（以及它 spawn 的 ``claude.exe``）只认 ``ANTHROPIC_*``。
两者不会自动互转——不做映射的话，用户在平台「模型管理」里绑的模型对
本包完全无效，SDK 会因为没有凭据而退化到 heuristic。

## 两条约束

**一、不能覆盖真实环境变量。** 本地开发时 ``.env`` 里写的是 ``ANTHROPIC_*``，
有值就说明作者有意指定，平台注入的值不该盖掉它。

**二、base_url 要做协议翻转。** 同一个网关通常同时开 ``/openai/`` 和
``/anthropic/`` 两套路径（Nexas 客户端自己的 ``q()`` 函数就是这么做的：
给 Sprite 用的 URL 把 ``/openai/`` 翻成 ``/anthropic/``）。``OPENAI_BASE_URL``
指向的是 OpenAI 协议端点，直接喂给 SDK 会 404。

## 注入方式

不写 ``os.environ``，而是返回一个 dict 交给 ``ClaudeAgentOptions.env``：

    process_env = {**inherited_env, ..., **self._options.env, ...}

SDK 在 spawn 子进程时按次覆盖，所以：
- 不污染当前进程（一次 run 换了 key 不会影响下一次）
- 多票并发/串行切换也不会互相干扰
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "PLATFORM_KEY_ENV",
    "PLATFORM_URL_ENV",
    "PLATFORM_MODEL_ENV",
    "flip_url_protocol",
    "model_from_env",
    "sdk_env_overrides",
    "sdk_options_env",
]

# Nexas 注入的三个变量名。刻意写死而不是做成配置项——这是平台契约，
# 不随部署变化。
PLATFORM_KEY_ENV = "OPENAI_API_KEY"
PLATFORM_URL_ENV = "OPENAI_BASE_URL"
PLATFORM_MODEL_ENV = "OPENAI_MODEL"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def flip_url_protocol(url: str) -> str:
    """把 OpenAI 协议端点改成 Anthropic 协议端点。

    ``http://gw/v3/openai/model`` → ``http://gw/v3/anthropic/model``

    只翻转路径段 ``/openai/``，不做别的猜测。判断"已经是 anthropic"的口径
    参考 Nexas 客户端自身：含 ``/anthropic/`` 或 ``anthropic.com`` 即认为是
    Anthropic 协议，原样返回。

    找不到 ``/openai/`` 时原样返回——宁可让网关报 404 暴露配置问题，
    也不要瞎拼一个不存在的路径。
    """
    raw = _clean(url)
    if not raw:
        return ""
    lowered = raw.lower()
    if "/anthropic/" in lowered or "anthropic.com" in lowered:
        return raw
    idx = lowered.find("/openai/")
    if idx < 0:
        return raw
    return raw[:idx] + "/anthropic/" + raw[idx + len("/openai/"):]


def sdk_env_overrides() -> dict[str, str]:
    """构造本次 SDK 会话要注入的环境变量。

    只返回**有值**的项，让 SDK 的 ``{**inherited, **options.env}`` 保持
    继承语义：返回空 dict 时行为与不传 ``env`` 完全一致。

    优先级：
    - 凭据：``ANTHROPIC_*`` 已有就不动；否则从 ``OPENAI_*`` 取。
    - base_url：同上，且从 ``OPENAI_BASE_URL`` 取时做协议翻转。
    - model：``ANTHROPIC_MODEL`` 优先，其次 ``OPENAI_MODEL``。
    """
    overrides: dict[str, str] = {}

    # --- 凭据 ---
    if not (_clean(os.environ.get("ANTHROPIC_API_KEY")) or _clean(os.environ.get("ANTHROPIC_AUTH_TOKEN"))):
        key = _clean(os.environ.get(PLATFORM_KEY_ENV))
        if key:
            # 平台给的是 bearer token 语义（Nexas 里叫 tokenKey），
            # 用 AUTH_TOKEN 而不是 API_KEY，避免 claude.exe 走 x-api-key 头。
            overrides["ANTHROPIC_AUTH_TOKEN"] = key

    # --- base_url ---
    if not _clean(os.environ.get("ANTHROPIC_BASE_URL")):
        url = _clean(os.environ.get(PLATFORM_URL_ENV))
        if url:
            flipped = flip_url_protocol(url)
            if flipped:
                overrides["ANTHROPIC_BASE_URL"] = flipped

    # --- model ---
    if not _clean(os.environ.get("ANTHROPIC_MODEL")):
        model = _clean(os.environ.get(PLATFORM_MODEL_ENV))
        if model:
            overrides["ANTHROPIC_MODEL"] = model

    return overrides


def model_from_env(explicit: str | None = None) -> str | None:
    """解析本次会话用的模型名。

    ``explicit`` 来自调用方（``AnalyzeRequest.model`` 等），优先级最高。
    其次 ``ANTHROPIC_MODEL``，再其次平台注入的 ``OPENAI_MODEL``。

    返回 ``None`` 表示"不指定"，让 SDK 用它自己的默认值。
    """
    if _clean(explicit):
        return _clean(explicit)
    for name in ("ANTHROPIC_MODEL", PLATFORM_MODEL_ENV):
        value = _clean(os.environ.get(name))
        if value:
            return value
    return None


def sdk_options_env(options: dict[str, Any]) -> dict[str, Any]:
    """给一份即将传给 ``ClaudeAgentOptions`` 的 kwargs 补上 ``env`` 与 ``cli_path``。

    两件事合在这里，因为它们都是「平台环境下必须补、本地环境下不需要」的项：

    - ``env``：平台注入 ``OPENAI_*``，映射成 ``ANTHROPIC_*``
    - ``cli_path``：包内不带 356 MB 的 ``claude.exe``，要用宿主自带的那份

    调用方显式写了的项一律不动。
    """
    if not options.get("env"):
        overrides = sdk_env_overrides()
        if overrides:
            options["env"] = overrides
    if not options.get("cli_path"):
        from bugfix_platform.sdk.claude_cli import cli_path_option

        options.update(cli_path_option())
    return options