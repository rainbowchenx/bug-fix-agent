"""受控检查执行。建议步骤不得记 passed；缺命令记 blocked。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from bugfix_contracts.repair import VerificationRun


def run_check(
    spec: dict[str, Any],
    workspace: Path,
    timeout_seconds: int = 120,
) -> VerificationRun:
    """跑一条已声明的检查命令。"""
    command = list(spec.get("command") or [])
    cwd = Path(spec.get("cwd") or workspace)
    timeout = int(spec.get("timeoutSeconds") or timeout_seconds)
    suggested = bool(spec.get("suggested"))
    if suggested:
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="not_run",
            coverage="suggested_only",
        )
    if not command:
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="blocked",
            coverage="empty_command",
        )
    bin_name = str(command[0])
    if shutil.which(bin_name) is None and not Path(bin_name).exists():
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="blocked",
            coverage="missing_binary",
        )
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="blocked",
            coverage="timeout",
        )
    except OSError:
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="blocked",
            coverage="exec_error",
        )
    result = "passed" if proc.returncode == 0 else "failed"
    return VerificationRun(
        command=command,
        cwd=str(cwd),
        timeoutSeconds=timeout,
        exitCode=proc.returncode,
        result=result,  # type: ignore[arg-type]
        coverage="executed",
    )
