"""Windows stdio launcher for one CodeGraph MCP process tree."""

from __future__ import annotations

import _winapi
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_uint64 * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_create_job = _kernel32.CreateJobObjectW
_create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
_create_job.restype = wintypes.HANDLE

_set_job_info = _kernel32.SetInformationJobObject
_set_job_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_set_job_info.restype = wintypes.BOOL

_assign_to_job = _kernel32.AssignProcessToJobObject
_assign_to_job.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_assign_to_job.restype = wintypes.BOOL

_get_process_times = _kernel32.GetProcessTimes
_get_process_times.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
_get_process_times.restype = wintypes.BOOL

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_creation_time(handle: int | None = None) -> int:
    """Use the same FILETIME identity in the host and launcher."""
    if handle is None:
        handle = _winapi.GetCurrentProcess()
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not _get_process_times(handle, *(ctypes.byref(t) for t in (created, exited, kernel, user))):
        raise ctypes.WinError(ctypes.get_last_error())
    return created.dwHighDateTime << 32 | created.dwLowDateTime


def _join_session_job() -> None:
    job = _create_job(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (
        _set_job_info(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits))
        and _assign_to_job(job, _winapi.GetCurrentProcess())
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        _winapi.CloseHandle(job)
        raise error
    # The launcher holds the only handle. Windows closes it when the launcher
    # exits, including when Claude kills it. All children inherit membership.


def _start_codegraph(command: list[str]) -> subprocess.Popen:
    executable = None
    env = None
    args: str | list[str] = command
    if Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
        executable = str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe")
        # Pass paths through quoted environment expansions to avoid interpreting
        # characters such as &, % or ! as cmd syntax in the executable or repo path.
        env = {
            **os.environ,
            "_BUGFIX_CODEGRAPH_EXECUTABLE": command[0],
            "_BUGFIX_CODEGRAPH_ROOT": command[-1],
        }
        args = (
            f'"{executable}" /d /s /v:off /c '
            '""%_BUGFIX_CODEGRAPH_EXECUTABLE%" serve --mcp -p "%_BUGFIX_CODEGRAPH_ROOT%""'
        )
    return subprocess.Popen(
        args,
        executable=executable,
        env=env,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run(owner_pid: int, owner_created: int, command: list[str]) -> int:
    parent_pid = os.getppid()
    launcher_created = process_creation_time()
    watches: list[int] = []
    try:
        for pid in dict.fromkeys((owner_pid, parent_pid)):
            try:
                handle = _winapi.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            except OSError as error:
                if error.winerror == 87:  # ERROR_INVALID_PARAMETER: the process has exited.
                    return 0
                raise
            watches.append(handle)
            created = process_creation_time(handle)
            if (pid == owner_pid and created != owner_created) or created > launcher_created:
                return 0
            if _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_OBJECT_0:
                return 0

        _join_session_job()
        child = _start_codegraph(command)
        child_handle = _winapi.OpenProcess(_SYNCHRONIZE, False, child.pid)
        watches.append(child_handle)
        result = _winapi.WaitForMultipleObjects(watches, False, _winapi.INFINITE)
        if result == _winapi.WAIT_OBJECT_0 + len(watches) - 1:
            return child.wait()
        return 0
    finally:
        for handle in watches:
            _winapi.CloseHandle(handle)


if __name__ == "__main__":
    try:
        raise SystemExit(_run(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]))
    except OSError as error:
        print(f"CodeGraph MCP launcher: {error}", file=sys.stderr)
        raise SystemExit(1) from None
