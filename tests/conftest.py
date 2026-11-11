"""全局测试守卫：测试永远不碰真实模型凭据。

起因是一次真实事故：`load_env_file()` 不传参在仓根跑了一次，把 `.env` 里的
`ANTHROPIC_*` 灌进整个 pytest 进程；后面 `test_langgraph_e2e_invoke` 直接
`graph.invoke({...})`（state 里没有 mode 键）→ 节点回落到 `mode_from_env(None)`
→ 真的开了 SDK 会话。症状是整套测试从 7s 变成 631s，而且是花钱跑。

所以这里在**每个用例开始前**清掉凭据与模式开关。用例想要环境变量，自己用
`monkeypatch.setenv` 设——那发生在 fixture 之后，不受影响。
"""

from __future__ import annotations

import pytest

_LEAKY = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "BUGFIX_CARTOGRAPHY_MODE",
    "BUGFIX_ANALYZE_MODE",
    "BUGFIX_CARTOGRAPHY_MAX_TURNS",
    "BUGFIX_APPLY_FIX",
    "BUGFIX_ANALYZE_MAX_TURNS",
)


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LEAKY:
        monkeypatch.delenv(key, raising=False)
