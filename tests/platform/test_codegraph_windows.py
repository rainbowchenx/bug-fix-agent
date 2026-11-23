"""Windows CodeGraph launcher process-tree regression tests."""

import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack

import pytest

from bugfix_platform.sdk.codegraph import CodeGraphStatus


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects")

_FAKE_CODEGRAPH = """\
import json
import os
import subprocess
import sys
import time

mode = sys.argv[1]
if mode == "serve":
    worker = subprocess.Popen(
        [sys.executable, __file__, "worker"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(json.dumps([os.getpid(), worker.pid]), flush=True)
    sys.stdin.buffer.read(1)
elif mode == "parent":
    subprocess.Popen(sys.argv[2:])
    time.sleep(30)
else:
    time.sleep(30)
"""


@pytest.mark.parametrize("shutdown", ["server", "launcher", "parent", "owner"])
def test_windows_codegraph_reaps_only_its_session_tree(tmp_path, shutdown):
    import _winapi

    from bugfix_platform.sdk._codegraph_windows import process_creation_time

    interpreter = sys._base_executable
    server_script = tmp_path / "fake CodeGraph.py"
    server_script.write_text(_FAKE_CODEGRAPH, encoding="utf-8")
    config = CodeGraphStatus(ready=True, bin=interpreter).mcp_servers(str(tmp_path))["codegraph"]

    with ExitStack() as cleanup:
        def start(command, **kwargs):
            process = subprocess.Popen(command, **kwargs)
            cleanup.callback(process.__exit__, None, None, None)
            cleanup.callback(process.kill)
            return process

        def watch(pid):
            access = 0x00100000 | 0x1000 | 0x0001  # Synchronize, query identity, terminate on test failure.
            handle = _winapi.OpenProcess(access, False, pid)
            cleanup.callback(_winapi.CloseHandle, handle)

            def terminate_if_running():
                if _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT:
                    _winapi.TerminateProcess(handle, 1)
            cleanup.callback(terminate_if_running)
            return handle

        def start_session(name, *, controller=False, owner=None):
            args = list(config["args"])
            args.insert(-4, str(server_script))
            if owner is not None:
                args[2:4] = [str(owner.pid), str(process_creation_time(watch(owner.pid)))]
            command = [config["command"], *args]
            if controller:
                command = [interpreter, str(server_script), "parent", *command]
            output = tmp_path / f"{name}.stdout"
            with output.open("wb") as stdout:
                process = start(command, stdin=subprocess.PIPE, stdout=stdout)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                line = output.read_text(encoding="utf-8")
                if line.endswith("\n"):
                    server_pid, worker_pid = json.loads(line)
                    return process, [watch(server_pid), watch(worker_pid)]
                if process.poll() is not None:
                    pytest.fail(f"launcher exited with {process.returncode} before starting CodeGraph")
                time.sleep(0.05)
            pytest.fail("CodeGraph did not write its process IDs to inherited stdout")

        other, other_tree = start_session("other")
        owner = start([interpreter, str(server_script), "worker"]) if shutdown == "owner" else None
        process, tree = start_session("target", controller=shutdown == "parent", owner=owner)
        if shutdown == "server":
            assert process.stdin is not None
            process.stdin.close()
        elif shutdown == "owner":
            owner.kill()
            owner.wait(timeout=10)
        else:
            process.kill()

        process.wait(timeout=10)
        if shutdown in {"server", "owner"}:
            assert process.returncode == 0
        assert [_winapi.WaitForSingleObject(handle, 10000) for handle in tree] == [
            _winapi.WAIT_OBJECT_0, _winapi.WAIT_OBJECT_0,
        ]
        assert other.poll() is None
        assert [_winapi.WaitForSingleObject(handle, 0) for handle in other_tree] == [
            _winapi.WAIT_TIMEOUT, _winapi.WAIT_TIMEOUT,
        ]


def test_windows_batch_launcher_preserves_literal_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_CODEGRAPH_PATH_SEGMENT", "expanded-by-cmd")
    folder = tmp_path / "repo & %TEST_CODEGRAPH_PATH_SEGMENT%!"
    folder.mkdir()
    batch = folder / "codegraph.cmd"
    batch.write_text('@echo off\nset /p "=<%~4>" <nul\nexit /b 0\n', encoding="ascii")
    server = CodeGraphStatus(ready=True, bin=str(batch)).mcp_servers(str(folder))["codegraph"]

    result = subprocess.run(
        [server["command"], *server["args"]],
        input="", capture_output=True, text=True, timeout=10, check=True,
    )
    assert result.stdout == f"<{folder}>"
