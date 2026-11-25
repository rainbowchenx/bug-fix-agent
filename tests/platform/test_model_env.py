"""平台模型注入 → SDK 变量映射。

Nexas OS 的 LangGraph 执行器注入 `OPENAI_API_KEY` / `OPENAI_BASE_URL` /
`OPENAI_MODEL`，而 Claude Agent SDK 只认 `ANTHROPIC_*`。映射不做的话，用户在
平台「模型管理」里绑的模型对本包完全无效，SDK 会静默退化成 heuristic。
"""

from __future__ import annotations

import pytest

from bugfix_platform.sdk.model_env import (
    flip_url_protocol,
    model_from_env,
    sdk_env_overrides,
    sdk_options_env,
)

_ALL = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "url, expected",
    [
        # 网关双协议路径：OpenAI 侧翻成 Anthropic 侧
        ("http://lanz.hikvision.com/v3/openai/model", "http://lanz.hikvision.com/v3/anthropic/model"),
        # 已经是 Anthropic 侧的不能重复翻
        ("http://lanz.hikvision.com/v3/anthropic/model", "http://lanz.hikvision.com/v3/anthropic/model"),
        # 官方端点没有 /openai/，原样返回
        ("https://api.anthropic.com", "https://api.anthropic.com"),
        # 不含 /openai/ 的第三方网关：不瞎拼路径
        ("http://gw/v1/chat", "http://gw/v1/chat"),
        ("", ""),
        ("   ", ""),
        # 大小写不敏感
        ("HTTP://GW/V3/OPENAI/MODEL", "HTTP://GW/V3/anthropic/MODEL"),
        # 只翻第一个 /openai/，其余保持原样
        ("http://gw/openai/v1/x/openai/y", "http://gw/anthropic/v1/x/openai/y"),
    ],
)
def test_flip_url_protocol(url, expected):
    assert flip_url_protocol(url) == expected


def test_maps_all_three_when_only_platform_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gw/v3/openai/model")
    monkeypatch.setenv("OPENAI_MODEL", "EB-DeepSeek-Flash")

    assert sdk_env_overrides() == {
        "ANTHROPIC_AUTH_TOKEN": "sk-platform",
        "ANTHROPIC_BASE_URL": "http://gw/v3/anthropic/model",
        "ANTHROPIC_MODEL": "EB-DeepSeek-Flash",
    }
    assert model_from_env() == "EB-DeepSeek-Flash"


def test_native_anthropic_wins(monkeypatch):
    """本地 .env 里写了 ANTHROPIC_* 就不该被平台注入的值覆盖。"""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-native")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-native")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gw/v3/openai/model")
    monkeypatch.setenv("OPENAI_MODEL", "EB-DeepSeek-Flash")

    assert sdk_env_overrides() == {}
    assert model_from_env() == "claude-native"


def test_partial_override_only_fills_gaps(monkeypatch):
    """原生只给了一部分时，只补缺失的项。"""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-native")
    monkeypatch.setenv("OPENAI_MODEL", "EB-DeepSeek-Flash")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://gw/v3/openai/model")

    assert sdk_env_overrides() == {
        "ANTHROPIC_BASE_URL": "http://gw/v3/anthropic/model",
        "ANTHROPIC_MODEL": "EB-DeepSeek-Flash",
    }


def test_blank_values_are_not_mapped(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.setenv("OPENAI_BASE_URL", "  ")
    monkeypatch.setenv("OPENAI_MODEL", "")

    assert sdk_env_overrides() == {}
    assert model_from_env() is None


def test_explicit_model_beats_everything(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "from-env")
    monkeypatch.setenv("OPENAI_MODEL", "from-platform")

    assert model_from_env("explicit") == "explicit"
    assert model_from_env("  explicit  ") == "explicit"


def test_sdk_options_env_injects(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform")

    options = sdk_options_env({"cwd": "."})
    assert options["env"] == {"ANTHROPIC_AUTH_TOKEN": "sk-platform"}


def test_sdk_options_env_respects_explicit(monkeypatch):
    """调用方自己写了 env 就原样保留，不覆盖。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform")

    options = sdk_options_env({"env": {"ANTHROPIC_AUTH_TOKEN": "explicit"}})
    assert options["env"] == {"ANTHROPIC_AUTH_TOKEN": "explicit"}


def test_sdk_options_env_noop_when_nothing_to_map():
    """既没有原生也没有平台变量时，不该凭空塞一个空 env 进去。"""
    assert "env" not in sdk_options_env({"cwd": "."})
