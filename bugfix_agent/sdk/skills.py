"""把包内 ``skills/`` 指给 Claude Agent SDK 会话。

这些 SOP（hierarchical-localization、systematic-debugging 等）随包发布。
Agent-2/3 会在 system prompt 末尾追加相关 skill 名；若 skill 目录可被
Claude Code 发现，也会加载对应 ``SKILL.md``。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional


def package_skills_root() -> Path:
    """随包发布的仓库根 ``skills/`` 目录。"""
    # bugfix_agent/sdk/skills.py → parents[2] == 仓库 / 包根。
    return Path(__file__).resolve().parents[2] / "skills"


@lru_cache(maxsize=1)
def list_package_skill_names() -> tuple[str, ...]:
    root = package_skills_root()
    if not root.is_dir():
        return ()
    names: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            names.append(child.name)
    return tuple(names)


def skills_system_addon(relevant: Optional[tuple[str, ...]] = None) -> str:
    """生成简短 system-prompt 附录，点名可用的包内 skills。

    Claude Code 在 skill 目录位于搜索路径时可自动发现 ``SKILL.md``；
    这里再显式点名，让 heuristic / SDK 会话共用同一套 SOP 词汇。
    """
    names = list(relevant) if relevant is not None else list(list_package_skill_names())
    if not names:
        return ""
    root = package_skills_root()
    listed = ", ".join(names)
    return (
        f"\nAvailable package skills under {root}: {listed}. "
        "When a skill matches the task, follow its SKILL.md procedure."
    )
