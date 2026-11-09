"""源码树按产品切开：Agent-1 与平台互不带对方模块 / skill。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = os.pathsep.join(
    str(ROOT / part) for part in ("contracts", "agent1", "platform")
)


def test_agent1_tree_has_no_platform_modules():
    import bugfix_agent1

    root = Path(bugfix_agent1.__file__).resolve().parent
    names = {p.name for p in root.iterdir()}
    assert "ingest" in names
    assert "defect_batch" in names
    assert "agents" not in names
    assert "workflow" not in names
    assert "sdk" not in names


def test_platform_tree_has_no_agent1_modules():
    import bugfix_platform

    root = Path(bugfix_platform.__file__).resolve().parent
    names = {p.name for p in root.iterdir()}
    assert "agents" in names
    assert "workflow" in names
    assert "sdk" in names
    assert "ingest" not in names
    assert "defect_batch" not in names


def test_agent1_skills_exclude_platform():
    skill_root = ROOT / "agent1" / "skills"
    names = [p.name for p in skill_root.iterdir() if (p / "SKILL.md").is_file()]
    assert names == ["defect-batch-prepare"]


def test_platform_skills_exclude_agent1():
    from bugfix_platform.sdk.skills import list_package_skill_names, package_skills_root

    root = package_skills_root()
    assert root == ROOT / "platform" / "skills"
    names = list_package_skill_names()
    assert "defect-batch-prepare" not in names
    assert "code-cartography" in names


def test_agent1_import_does_not_load_langgraph_or_platform():
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    subprocess.check_call(
        [
            sys.executable,
            "-c",
            "import bugfix_agent1, sys; "
            "assert 'langgraph' not in sys.modules; "
            "assert 'bugfix_platform' not in sys.modules",
        ],
        cwd=ROOT,
        env=env,
    )


def test_platform_import_does_not_load_agent1():
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    subprocess.check_call(
        [
            sys.executable,
            "-c",
            "import bugfix_platform, sys; "
            "assert 'bugfix_agent1' not in sys.modules",
        ],
        cwd=ROOT,
        env=env,
    )
