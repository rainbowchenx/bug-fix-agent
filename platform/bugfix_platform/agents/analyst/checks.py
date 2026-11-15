"""受控检查执行。建议步骤不得记 passed；缺命令记 blocked。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from bugfix_contracts.repair import VerificationRun


def run_check(
    spec: dict[str, Any],
    workspace: Path,
    timeout_seconds: int = 120,
    *,
    log_dir: Path | None = None,
) -> VerificationRun:
    """跑一条已声明的检查命令。cwd 必须落在候选工作区内。"""
    command = list(spec.get("command") or [])
    workspace = Path(workspace).resolve()
    cwd = _constrained_cwd(spec.get("cwd"), workspace)
    timeout = int(spec.get("timeoutSeconds") or timeout_seconds)
    suggested = bool(spec.get("suggested"))
    archive = Path(log_dir) if log_dir is not None else None
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
    except subprocess.TimeoutExpired as err:
        log_ref = _write_log(
            workspace,
            _decode(err.stdout) + "\n" + _decode(err.stderr) + "\ntimeout",
            archive=archive,
        )
        return VerificationRun(
            command=command,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            result="blocked",
            coverage="timeout",
            logRef=log_ref,
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
    log_ref = _write_log(
        workspace,
        _decode(proc.stdout) + _decode(proc.stderr),
        archive=archive,
    )
    return VerificationRun(
        command=command,
        cwd=str(cwd),
        timeoutSeconds=timeout,
        exitCode=proc.returncode,
        result=result,  # type: ignore[arg-type]
        coverage="executed",
        logRef=log_ref,
    )


def _constrained_cwd(spec_cwd: Any, workspace: Path) -> Path:
    """相对路径相对候选目录；越出候选则钳回候选，不改写执行记录。"""
    if not spec_cwd:
        return workspace
    raw = Path(str(spec_cwd))
    cand = raw if raw.is_absolute() else (workspace / raw)
    try:
        resolved = cand.resolve()
        resolved.relative_to(workspace)
        return resolved
    except (ValueError, OSError):
        return workspace


def _decode(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _write_log(workspace: Path, text: str, *, archive: Path | None = None) -> str | None:
    if not (text or "").strip():
        return None
    dest_dir = Path(archive) if archive is not None else Path(workspace) / ".bugfix" / "check-logs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid4().hex[:12]}.log"
    dest.write_text(text, encoding="utf-8")
    return str(dest)
