"""Agent-1 onefile 不得把宿主 site-packages 里的 numpy / OpenBLAS 打进去。

回归：本机 Python 装了 numpy 时，openpyxl.compat.numbers 的可选 import 会把
约 20 MB 的 libscipy_openblas 拖进 exe，产物从 ~10 MB 膨胀到 ~26 MB。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _build_module():
    spec = importlib.util.spec_from_file_location(
        "_packaging_build", ROOT / "packaging" / "build.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_mod():
    return _build_module()


def test_agent1_pyinstaller_excludes_numpy_and_optional_leaks(build_mod):
    excludes = set(build_mod.AGENT1_PYINSTALLER_EXCLUDES)
    for name in ("numpy", "yaml", "chardet"):
        assert name in excludes, f"{name} must be --exclude-module (host-env leak)"


def test_agent1_pyinstaller_argv_uses_the_exclude_list(build_mod):
    argv = build_mod.agent1_pyinstaller_args(
        entry=Path("entry.py"),
        vendor_json=Path("VENDOR.json"),
        dist=Path("dist"),
        work=Path("work"),
        spec=Path("spec"),
    )
    flags = list(zip(argv, argv[1:]))
    excluded = {value for flag, value in flags if flag == "--exclude-module"}
    assert "numpy" in excluded
    assert "langgraph" in excluded
    assert "bugfix_platform" in excluded


def test_oversized_exe_fails_the_agent1_size_gate(tmp_path: Path, build_mod):
    exe = tmp_path / ("agent1.exe" if os.name == "nt" else "agent1")
    exe.write_bytes(b"x" * (20 * 1024 * 1024))
    with pytest.raises(SystemExit, match="too large|numpy"):
        build_mod._check_agent1_exe_size(exe)


def test_historical_10mb_exe_passes_the_agent1_size_gate(tmp_path: Path, build_mod):
    exe = tmp_path / ("agent1.exe" if os.name == "nt" else "agent1")
    exe.write_bytes(b"x" * (10 * 1024 * 1024))
    build_mod._check_agent1_exe_size(exe)
