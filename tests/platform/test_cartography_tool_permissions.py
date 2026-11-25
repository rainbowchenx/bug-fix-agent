"""T4：写 Bash 必须在 SDK 执行路由上被拦，不能只测 callback。"""

from __future__ import annotations

import pytest

from bugfix_platform.sdk.cartography import (
    bash_command_allowed,
    cartography_allowed_tools,
    _cartography_hooks,
)


def test_readonly_bash_allowed():
    assert bash_command_allowed("rg -n login src")[0] is True
    assert bash_command_allowed("git blame src/a.ts")[0] is True


def test_write_bash_denied_before_execution():
    for cmd in (
        "echo hi > /tmp/sentinel",
        "echo hi >> /tmp/sentinel",
        "tee /tmp/sentinel",
        "python -c \"open('/tmp/sentinel','w').write('x')\"",
    ):
        ok, reason = bash_command_allowed(cmd)
        assert ok is False, cmd
        assert "blocked" in reason


@pytest.mark.parametrize("supported", [False, True])
def test_options_install_pretooluse_hook(monkeypatch, supported):
    from bugfix_platform.sdk import claude_cli

    monkeypatch.setattr(claude_cli, "hook_on_failure_supported", lambda: supported)
    hooks = _cartography_hooks()
    if not hooks:
        assert "Bash" not in cartography_allowed_tools()
        pytest.skip("claude-agent-sdk missing; Bash not enabled without PreToolUse hook")
    matcher = hooks["PreToolUse"][0]
    assert matcher.matcher == "Bash"
    assert matcher.on_failure == ("block" if supported else None)
    assert matcher.hooks
    assert "Bash" not in cartography_allowed_tools()


def test_write_command_denied_by_installed_hook_does_not_create_sentinel(tmp_path):
    hooks = _cartography_hooks()
    if not hooks:
        pytest.skip("offline SDK hook unavailable; live CLI gate is an S criterion")
    import anyio

    sentinel = tmp_path / "sentinel.txt"
    hook = hooks["PreToolUse"][0].hooks[0]

    async def run():
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": f"echo hi > {sentinel}"}},
            None,
            None,
        )
        decision = (result.get("hookSpecificOutput") or {}).get("permissionDecision")
        if decision != "deny":
            sentinel.write_text("executed", encoding="utf-8")
        return decision

    assert anyio.run(run) == "deny"
    assert not sentinel.exists()
