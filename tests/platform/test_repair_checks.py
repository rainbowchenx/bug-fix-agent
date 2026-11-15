"""T06：缺依赖 blocked；建议步骤不能记 passed。"""

from __future__ import annotations

import sys
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


def test_cwd_outside_workspace_does_not_run_there(tmp_path: Path):
    workspace = tmp_path / "wt"
    workspace.mkdir()
    outside = tmp_path / "source"
    outside.mkdir()
    (outside / "secret.txt").write_text("src\n", encoding="utf-8")
    run = run_check(
        {
            "command": [sys.executable, "-c", "open('RAN.txt','w').write('1')"],
            "cwd": str(outside),
        },
        workspace,
        timeout_seconds=5,
    )
    assert not (outside / "RAN.txt").is_file()
    recorded = Path(run.cwd).resolve()
    assert recorded == workspace.resolve() or str(workspace.resolve()) in str(recorded)
    assert run.cwd != str(outside)


def test_failed_check_writes_stdout_to_logref(tmp_path: Path):
    workspace = tmp_path / "wt"
    workspace.mkdir()
    run = run_check(
        {
            "command": [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('camera_disconnected not handled\\n'); sys.exit(1)",
            ]
        },
        workspace,
        timeout_seconds=5,
    )
    assert run.result == "failed"
    assert run.logRef
    log = Path(run.logRef)
    if not log.is_file():
        log = workspace / run.logRef
    assert log.is_file()
    assert "camera_disconnected" in log.read_text(encoding="utf-8", errors="replace")


def test_log_dir_keeps_archive_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "wt"
    workspace.mkdir()
    archive = tmp_path / "attempts" / "a1" / "checks"
    run = run_check(
        {
            "command": [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('round1-unique-log\\n'); sys.exit(1)",
            ]
        },
        workspace,
        timeout_seconds=5,
        log_dir=archive,
    )
    assert run.logRef
    stored = Path(run.logRef)
    assert stored.is_file()
    assert archive.resolve() in stored.resolve().parents or stored.parent.resolve() == archive.resolve()
    assert "round1-unique-log" in stored.read_text(encoding="utf-8", errors="replace")


def test_timeout_bytes_output_is_blocked_not_crash(tmp_path: Path, monkeypatch):
    import subprocess

    workspace = tmp_path / "wt"
    workspace.mkdir()

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired(
            cmd=["slow"],
            timeout=1,
            output=b"stdout-bytes",
            stderr=b"stderr-bytes",
        )

    monkeypatch.setattr(subprocess, "run", boom)
    run = run_check({"command": [sys.executable, "-c", "pass"]}, workspace, timeout_seconds=1)
    assert run.result == "blocked"
    assert run.coverage == "timeout"
    if run.logRef:
        text = Path(run.logRef).read_text(encoding="utf-8", errors="replace")
        assert "stdout-bytes" in text or "stderr-bytes" in text or "timeout" in text
