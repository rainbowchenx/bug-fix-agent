"""`.env` 必须真的生效，否则 README 里的 `cp .env.example .env` 是摆设。

这里同时钉住"真实环境变量优先"——平台注入的凭据不能被仓里的 .env 改掉。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from bugfix_contracts.env import ENV_FILE_VAR, load_env_file


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in ("BFX_A", "BFX_B", "BFX_EMPTY", "BFX_QUOTED", BUGFIX_MARK := "BFX_MARK"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    yield


def test_missing_file_is_noop(tmp_path: Path):
    assert load_env_file(tmp_path / "nope.env") == {}


def test_parses_values_quotes_and_comments(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "\n"
        "BFX_A=plain\n"
        "export BFX_B=exported\n"
        "BFX_EMPTY=\n"
        "BFX_QUOTED='有空格 的值'\n"
        "not a pair\n",
        encoding="utf-8",
    )
    applied = load_env_file(env)
    assert applied["BFX_A"] == "plain"
    assert applied["BFX_B"] == "exported"
    assert applied["BFX_EMPTY"] == ""          # 空串保持空串，不塞 None
    assert applied["BFX_QUOTED"] == "有空格 的值"
    assert os.environ["BFX_A"] == "plain"


def test_real_env_wins_over_dotenv(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("BFX_A=from-file\nBFX_MARK=from-file\n", encoding="utf-8")
    monkeypatch.setenv("BFX_A", "from-real-env")

    applied = load_env_file(env)
    assert os.environ["BFX_A"] == "from-real-env"   # 不被覆盖
    assert "BFX_A" not in applied
    assert applied["BFX_MARK"] == "from-file"


def test_override_flag_for_explicit_calls(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("BFX_A=from-file\n", encoding="utf-8")
    monkeypatch.setenv("BFX_A", "from-real-env")
    load_env_file(env, override=True)
    assert os.environ["BFX_A"] == "from-file"


def test_env_file_var_points_elsewhere(tmp_path: Path, monkeypatch):
    env = tmp_path / "custom.env"
    env.write_text("BFX_B=custom\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(env))
    assert load_env_file()["BFX_B"] == "custom"


def test_both_clis_load_cwd_dotenv(tmp_path: Path, monkeypatch, capsys):
    """两个 CLI 的 main() 都要在碰 os.environ 之前读 .env。"""
    (tmp_path / ".env").write_text("BFX_MARK=loaded-by-cli\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from bugfix_agent1 import cli as agent1_cli

    with pytest.raises(SystemExit):
        agent1_cli.main(["--help"])
    assert os.environ["BFX_MARK"] == "loaded-by-cli"

    monkeypatch.delenv("BFX_MARK")
    from bugfix_platform import cli as platform_cli

    with pytest.raises(SystemExit):
        platform_cli.main(["--help"])
    assert os.environ["BFX_MARK"] == "loaded-by-cli"
