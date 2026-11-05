from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional


def package_skills_root() -> Path:
    """Repo/package `skills/` directory shipped with bugfix-agent."""
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
    """Short system-prompt addon pointing the SDK session at package skills.

    Claude Code discovers ``SKILL.md`` when the skill dir is on the agent
    search path; we also name them explicitly so heuristic/SDK sessions share
    the same SOP vocabulary.
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
