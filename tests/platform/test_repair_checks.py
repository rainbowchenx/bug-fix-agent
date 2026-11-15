"""T06：缺依赖 blocked；建议步骤不能记 passed。"""

from __future__ import annotations

from pathlib import Path

from bugfix_platform.agents.analyst.checks import run_check


def test_missing_command_is_blocked(tmp_path: Path):
    run = run_check(
        {"command": ["bugfix-repair-missing-bin-xyz"], "cwd": str(tmp_path), "timeoutSeconds": 5},
        tmp_path,
        timeout_seconds=5,
    )
    assert run.result == "blocked"
    assert run.exitCode != 0 or run.exitCode is None


def test_suggested_steps_do_not_count_as_passed(tmp_path: Path):
    run = run_check(
        {"command": ["echo", "please verify on device"], "cwd": str(tmp_path), "suggested": True},
        tmp_path,
        timeout_seconds=5,
    )
    assert run.result != "passed"
