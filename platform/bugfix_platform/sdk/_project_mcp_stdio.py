"""Launch an approved business MCP stdio server in its configured repository."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main(args: list[str]) -> int:
    if os.name != "nt":
        repo, command, *rest = args
        os.chdir(repo)
        os.execvp(command, [command, *rest])

    # This file is invoked with -I, so import only from its installed directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _codegraph_windows import run_in_session_job, start_stdio

    owner_pid, owner_created, repo, command, *rest = args
    os.chdir(repo)
    executable = shutil.which(command) or command
    return run_in_session_job(
        int(owner_pid), int(owner_created), lambda: start_stdio([executable, *rest]),
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except OSError as error:
        print(f"Project MCP launcher: {error}", file=sys.stderr)
        raise SystemExit(1) from None
