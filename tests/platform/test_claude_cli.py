"""``claude.exe`` 定位：包里不带 356 MB 的 bundled exe，改用宿主自带的那份。

背景：``claude_agent_sdk`` 的 wheel 有 179 MB，解压后 357 MB —— 其中 356 MB 是
``_bundled/claude.exe``，纯 Python 代码只有 0.5 MB。而 Artifactory 上那个 wheel
需要认证（401），内网 pip 装不下来。所以打包只 vendor 代码，CLI 运行时再找。
"""

from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import SimpleNamespace

import pytest

from bugfix_platform.sdk.claude_cli import (
    _exe_from_cmd_shim,
    cli_path_option,
    find_claude_cli,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """隔离环境：清掉显式变量，避免命中构建机上的真实安装。"""
    monkeypatch.delenv("BUGFIX_CLAUDE_CLI", raising=False)


def test_explicit_env_wins(monkeypatch, tmp_path):
    fake = tmp_path / "claude.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("BUGFIX_CLAUDE_CLI", str(fake))

    assert find_claude_cli() == fake.resolve()
    assert cli_path_option() == {"cli_path": str(fake.resolve())}


def test_explicit_env_ignored_when_missing(monkeypatch):
    monkeypatch.setenv("BUGFIX_CLAUDE_CLI", "Z:/nope/claude.exe")
    # 不该因为路径不存在就崩，继续走后面的分支
    assert isinstance(find_claude_cli(), (Path, type(None)))


@pytest.mark.skipif(sys.platform != "win32", reason="npm 垫片是 Windows 专有")
def test_parses_npm_cmd_shim(tmp_path):
    """npm 全局安装生成 .CMD 垫片，真正的 exe 在子目录里。"""
    real = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"MZ")

    shim = tmp_path / "claude.CMD"
    shim.write_text(
        "@ECHO off\r\n"
        "GOTO start\r\n"
        ":find_dp0\r\n"
        "SET dp0=%~dp0\r\n"
        "EXIT /b\r\n"
        ":start\r\n"
        "SETLOCAL\r\n"
        "CALL :find_dp0\r\n"
        '"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\r\n',
        encoding="utf-8",
    )

    assert _exe_from_cmd_shim(shim) == real.resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="npm 垫片是 Windows 专有")
def test_shim_without_exe_returns_none(tmp_path):
    shim = tmp_path / "claude.CMD"
    shim.write_text("@ECHO off\r\necho hi\r\n", encoding="utf-8")

    assert _exe_from_cmd_shim(shim) is None


def test_missing_shim_returns_none(tmp_path):
    assert _exe_from_cmd_shim(tmp_path / "nope.CMD") is None


def test_cli_path_option_empty_when_not_found(monkeypatch):
    """找不到时返回空 dict —— 调用方 ``kwargs.update()`` 保持无副作用。"""
    import bugfix_platform.sdk.claude_cli as mod

    monkeypatch.setattr(mod, "find_claude_cli", lambda: None)
    assert mod.cli_path_option() == {}


@pytest.mark.parametrize(("platform", "executable"), [("win32", "claude.exe"), ("linux", "claude")])
def test_bundled_sdk_cli_used_for_options_and_hook_probe(tmp_path, monkeypatch, platform, executable):
    import bugfix_platform.sdk.claude_cli as mod

    sdk = tmp_path / "claude_agent_sdk"
    cli = sdk / "_bundled" / executable
    cli.parent.mkdir(parents=True)
    cli.touch()
    spec = ModuleSpec("claude_agent_sdk", loader=None, is_package=True)
    spec.submodule_search_locations = [str(sdk)]
    monkeypatch.setattr(mod, "find_spec", lambda name: spec if name == spec.name else None)
    monkeypatch.setattr(mod, "_cli_beside_runner", lambda: None)
    monkeypatch.setattr(mod, "_from_process_tree", lambda: None)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.sys, "platform", platform)
    assert mod.cli_path_option() == {"cli_path": str(cli.resolve())}

    def version(command, **kwargs):
        assert command == [str(cli.resolve()), "--version"]
        return SimpleNamespace(returncode=0, stdout="2.1.326 (Claude Code)", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", version)
    assert mod.cli_supports_hook_on_failure() is True


@pytest.mark.skipif(sys.platform != "win32", reason="需要真实 claude.exe 做版本探测")
def test_hook_on_failure_version_gate():
    """老版本 CLI 不支持 hook 的 onFailure，要按版本降级。

    实测分界：Nexas 自带的 2.1.314 不支持（initialize 直接报错），
    npm 的 2.1.326 支持。
    """
    from bugfix_platform.sdk.claude_cli import cli_supports_hook_on_failure

    nexas = Path(r"D:\xietong\Nexas OS\resources\code-sprite-cli\claude.exe")
    if not nexas.is_file():
        pytest.skip("Nexas 未安装")

    # 2.1.314 低于门槛
    assert cli_supports_hook_on_failure(nexas) is False


def test_hook_gate_defaults_to_false_when_cli_missing(monkeypatch):
    """CLI 找不到时按不支持处理 —— 宁可少一层保护，也别让会话起不来。"""
    import bugfix_platform.sdk.claude_cli as mod

    monkeypatch.setattr(mod, "find_claude_cli", lambda: None)
    assert mod.cli_supports_hook_on_failure() is False
