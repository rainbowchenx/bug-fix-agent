"""凭据判定：API key 与 bearer token 同等对待。

`.env.example` 自己推荐的网关配法用的是 `ANTHROPIC_AUTH_TOKEN`；只认
`ANTHROPIC_API_KEY` 会让这种部署静默退化成 heuristic，还对外说「heuristic mode」。
"""

from __future__ import annotations

import pytest

from bugfix_platform.sdk.analyze import analyze_mode_from_env
from bugfix_platform.sdk.cartography import cartography_mode_from_env
from bugfix_platform.sdk.credentials import credentials_env_name, has_credentials

_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "BUGFIX_CARTOGRAPHY_MODE",
    "BUGFIX_ANALYZE_MODE",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "env, expected",
    [
        ({}, None),
        ({"ANTHROPIC_API_KEY": "sk-x"}, "ANTHROPIC_API_KEY"),
        ({"ANTHROPIC_AUTH_TOKEN": "bearer-x"}, "ANTHROPIC_AUTH_TOKEN"),
        ({"ANTHROPIC_API_KEY": "a", "ANTHROPIC_AUTH_TOKEN": "b"}, "ANTHROPIC_API_KEY"),
        # `.env` 里留 `KEY=` 的空占位不算凭据
        ({"ANTHROPIC_API_KEY": "   "}, None),
    ],
)
def test_credentials_env_name(monkeypatch, env, expected):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert credentials_env_name() == expected
    assert has_credentials() is (expected is not None)


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_either_credential_auto_enables_sdk(monkeypatch, name):
    monkeypatch.setenv(name, "x")
    assert cartography_mode_from_env(None) == "sdk"
    assert analyze_mode_from_env(None) == "sdk"


def test_whitespace_is_not_a_credential(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "  ")
    assert cartography_mode_from_env(None) == "heuristic"
    assert analyze_mode_from_env(None) == "heuristic"


def test_explicit_mode_beats_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert cartography_mode_from_env("heuristic") == "heuristic"
    assert analyze_mode_from_env("heuristic") == "heuristic"


def test_env_mode_beats_autodetect(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("BUGFIX_CARTOGRAPHY_MODE", "heuristic")
    monkeypatch.setenv("BUGFIX_ANALYZE_MODE", "heuristic")
    assert cartography_mode_from_env(None) == "heuristic"
    assert analyze_mode_from_env(None) == "heuristic"
