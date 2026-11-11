"""发现并合并 Agent-2 / Agent-3 可注入的仓特异性 skill。

优先级（同名后者覆盖；提示词里 overlay 永远压过包内置）::

    包内置 → 仓内 ``.claude/skills`` → ``workDir/.bugfix/skills``
    → ``--skills-dir`` / ``BUGFIX_SKILLS_DIR``

Profile 过滤（frontmatter 顶层或 ``metadata.profiles``）：

- ``cartography`` → Agent-2
- ``analyze`` → Agent-3 只读分析
- ``fix`` → Agent-3 ``--apply-fix`` 改码会话
- ``bugfix`` → 两边都加载（推荐给线别 overlay）
- ``.bugfix/skills`` / ``--skills-dir`` 未写 profiles 的，默认两边都加载

指导怎么读这个仓、测试/开发习惯、模块别名；不改契约门禁。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional, Sequence

from bugfix_contracts.code_knowledge import RepoRoot
from bugfix_platform.sdk.skills import package_skills_root

CARTOGRAPHY_PROFILE = "cartography"
ANALYZE_PROFILE = "analyze"
FIX_PROFILE = "fix"
BUGFIX_PROFILE = "bugfix"
PACKAGE_CARTOGRAPHY_SKILLS = (
    "code-cartography",
    "monorepo-workspace",
    "electron-process-boundary",
    "hierarchical-localization",
)
PACKAGE_ANALYZE_SKILLS = (
    "hierarchical-localization",
    "systematic-debugging",
    "test-triage",
    "typescript-null-safety",
    "vue-debug",
    "electron-process-boundary",
    "monorepo-workspace",
)
PACKAGE_FIX_SKILLS = (
    "hierarchical-localization",
    "systematic-debugging",
    "typescript-null-safety",
    "vue-debug",
    "electron-process-boundary",
    "monorepo-workspace",
)
_MAX_BODY_CHARS = 2400
_SOURCE_RANK = {"explicit": 0, "bugfix": 1, "claude_dir": 2, "package": 3}
SkillSource = Literal["package", "claude_dir", "bugfix", "explicit"]


@dataclass(frozen=True)
class InjectedSkill:
    """一份已解析的注入 skill。"""

    name: str
    skill_md: Path
    source: SkillSource
    description: str
    body: str
    profiles: tuple[str, ...]


def extra_skill_dirs_from_env() -> list[Path]:
    """从 ``BUGFIX_SKILLS_DIR``（os.pathsep 分隔）读额外 skill 根目录。"""
    raw = (os.environ.get("BUGFIX_SKILLS_DIR") or "").strip()
    if not raw:
        return []
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


def discover_cartography_skills(
    work_dir: str | Path,
    repo_roots: Sequence[RepoRoot] | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
) -> list[InjectedSkill]:
    """发现 Agent-2 cartography skill（overlay 在前）。"""
    return discover_injected_skills(
        work_dir,
        repo_roots=repo_roots,
        extra_dirs=extra_dirs,
        profile=CARTOGRAPHY_PROFILE,
    )


def discover_analyze_skills(
    work_dir: str | Path,
    repo_roots: Sequence[RepoRoot] | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
) -> list[InjectedSkill]:
    """发现 Agent-3 analyze skill（overlay 在前）。"""
    return discover_injected_skills(
        work_dir,
        repo_roots=repo_roots,
        extra_dirs=extra_dirs,
        profile=ANALYZE_PROFILE,
    )


def discover_fix_skills(
    work_dir: str | Path,
    repo_roots: Sequence[RepoRoot] | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
) -> list[InjectedSkill]:
    """发现 Agent-3 ``--apply-fix`` 改码 skill（overlay 在前）。"""
    return discover_injected_skills(
        work_dir,
        repo_roots=repo_roots,
        extra_dirs=extra_dirs,
        profile=FIX_PROFILE,
    )


def discover_injected_skills(
    work_dir: str | Path,
    repo_roots: Sequence[RepoRoot] | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
    *,
    profile: str,
) -> list[InjectedSkill]:
    """按 merge 顺序发现指定 profile 的 skill。

    Args:
        work_dir: 目标代码根。
        repo_roots: 已发现的仓根；缺省只扫 ``work_dir`` 自身。
        extra_dirs: Run 级注入目录（每个目录下是 skill 文件夹）。
        profile: ``cartography`` / ``analyze`` / ``fix``。

    Returns:
        overlay（显式 / ``.bugfix`` / 仓内）在前、包内置在后；同名已按来源覆盖。
    """
    root = Path(work_dir)
    match_profiles = frozenset({profile, BUGFIX_PROFILE})
    by_name: dict[str, InjectedSkill] = {}

    def absorb(skills: Iterable[InjectedSkill]) -> None:
        for skill in skills:
            by_name[skill.name] = skill

    absorb(_package_skills(match_profiles))
    roots = list(repo_roots) if repo_roots else []
    if not roots:
        roots = [RepoRoot(path=".")]
    for rr in roots:
        abs_path = root if rr.path in (".", "") else root / rr.path
        absorb(
            _skills_in_dir(
                abs_path / ".claude" / "skills",
                source="claude_dir",
                match_profiles=match_profiles,
                allow_unprofiled=False,
            )
        )
    absorb(
        _skills_in_dir(
            root / ".bugfix" / "skills",
            source="bugfix",
            match_profiles=match_profiles,
            allow_unprofiled=True,
        )
    )
    for extra in list(extra_dirs or []) + extra_skill_dirs_from_env():
        absorb(
            _skills_in_dir(
                Path(extra),
                source="explicit",
                match_profiles=match_profiles,
                allow_unprofiled=True,
            )
        )
    return _priority_order(by_name.values())


def injected_skills_addon(
    skills: Sequence[InjectedSkill],
    *,
    agent: str,
    hard_limits: str,
) -> str:
    """生成 system-prompt 附录：overlay 正文优先，包内置仅作退路。"""
    if not skills:
        return ""
    overlay = [s for s in skills if s.source != "package"]
    package = [s for s in skills if s.source == "package"]
    lines: list[str] = []
    if overlay:
        lines.append(
            f"\n## HIGHEST PRIORITY — repo-specific {agent} skills\n"
            "These overlay skills outrank package SOP and generic heuristics. "
            "Follow them whenever they apply. "
            f"{hard_limits}"
        )
        for skill in overlay:
            lines.extend(_skill_excerpt(skill, include_body=True))
    if package:
        lines.append(
            "\n## Package SOP (fallback only when overlay skills do not cover the situation)"
        )
        for skill in package:
            lines.extend(_skill_excerpt(skill, include_body=False))
    return "\n".join(lines)


def cartography_skills_addon(skills: Sequence[InjectedSkill]) -> str:
    """Agent-2 system-prompt 附录。"""
    return injected_skills_addon(
        skills,
        agent="cartography",
        hard_limits=(
            "They never invent paths, never exceed 3 candidates per ticket, "
            "and never match outside strict/locatable_only/needs_info."
        ),
    )


def analyze_skills_addon(skills: Sequence[InjectedSkill]) -> str:
    """Agent-3 system-prompt 附录。"""
    return injected_skills_addon(
        skills,
        agent="analyze",
        hard_limits=(
            "They never invent paths, never edit the repo, and never invent "
            "outcome / schema fields outside the analysis-report contract."
        ),
    )


def fix_skills_addon(skills: Sequence[InjectedSkill]) -> str:
    """Agent-3 apply-fix system-prompt 附录。"""
    return injected_skills_addon(
        skills,
        agent="fix",
        hard_limits=(
            "Minimal diff only. Stay inside proposedFix.targetFiles unless a "
            "file you read proves another file is required. Never commit or push."
        ),
    )


def _priority_order(skills: Iterable[InjectedSkill]) -> list[InjectedSkill]:
    items = list(skills)
    overlay = sorted(
        [s for s in items if s.source != "package"],
        key=lambda s: (_SOURCE_RANK.get(s.source, 9), s.name.lower()),
    )
    package = [s for s in items if s.source == "package"]
    return overlay + package


def _skill_excerpt(skill: InjectedSkill, *, include_body: bool) -> list[str]:
    lines = [f"\n### {skill.name} ({skill.source}) — {skill.skill_md}"]
    if skill.description:
        lines.append(skill.description.strip())
    if include_body and skill.body.strip():
        excerpt = skill.body.strip()
        if len(excerpt) > _MAX_BODY_CHARS:
            excerpt = excerpt[:_MAX_BODY_CHARS] + "\n…"
        lines.append(excerpt)
    else:
        lines.append("When this skill matches, follow its SKILL.md procedure.")
    return lines


def _package_skills(match_profiles: frozenset[str]) -> list[InjectedSkill]:
    root = package_skills_root()
    if not root.is_dir():
        return []
    allow: set[str] = set()
    if CARTOGRAPHY_PROFILE in match_profiles:
        allow.update(PACKAGE_CARTOGRAPHY_SKILLS)
    if ANALYZE_PROFILE in match_profiles:
        allow.update(PACKAGE_ANALYZE_SKILLS)
    if FIX_PROFILE in match_profiles:
        allow.update(PACKAGE_FIX_SKILLS)
    found: dict[str, InjectedSkill] = {}
    for child in sorted(root.iterdir()):
        skill = _load_skill(child / "SKILL.md", source="package")
        if skill is None:
            continue
        profiles = set(skill.profiles)
        if skill.name in allow or profiles & match_profiles:
            found[skill.name] = skill
    return list(found.values())


def _skills_in_dir(
    directory: Path,
    *,
    source: SkillSource,
    match_profiles: frozenset[str],
    allow_unprofiled: bool,
) -> list[InjectedSkill]:
    if not directory.is_dir():
        return []
    out: list[InjectedSkill] = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    for child in sorted(children, key=lambda p: p.name.lower()):
        if child.is_file() and child.name == "SKILL.md":
            skill_md = child
        elif child.is_dir() and (child / "SKILL.md").is_file():
            skill_md = child / "SKILL.md"
        else:
            continue
        skill = _load_skill(skill_md, source=source)
        if skill is None:
            continue
        if not _matches_agent(skill, match_profiles, allow_unprofiled=allow_unprofiled):
            continue
        out.append(skill)
    return out


def _matches_agent(
    skill: InjectedSkill,
    match_profiles: frozenset[str],
    *,
    allow_unprofiled: bool,
) -> bool:
    profiles = set(skill.profiles)
    if profiles & match_profiles:
        return True
    if allow_unprofiled and not profiles:
        return True
    return False


def _load_skill(skill_md: Path, *, source: SkillSource) -> Optional[InjectedSkill]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _split_frontmatter(text)
    name = _frontmatter_scalar(fm, "name") or skill_md.parent.name
    if not name.strip():
        return None
    return InjectedSkill(
        name=name.strip(),
        skill_md=skill_md.resolve(),
        source=source,
        description=_frontmatter_scalar(fm, "description"),
        body=body,
        profiles=_frontmatter_profiles(fm),
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    rest = text[3:].lstrip("\r\n")
    end = re.search(r"\n---\s*\n", rest)
    if not end:
        return "", text
    return rest[: end.start()], rest[end.end() :]


def _frontmatter_scalar(fm: str, key: str) -> str:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(.+)$", fm)
    if not m:
        return ""
    raw = m.group(1).strip()
    if raw in {">", ">-", "|", "|-"}:
        return ""
    return raw.strip("\"'")


def _frontmatter_profiles(fm: str) -> tuple[str, ...]:
    found: list[str] = []
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)profiles:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        rest = m.group(2).strip()
        if rest and rest not in {">", ">-", "|", "|-"}:
            raw = rest.strip("[]")
            found.extend(p.strip().strip("\"'") for p in re.split(r"[, ]+", raw) if p.strip())
            i += 1
            continue
        indent = len(m.group(1))
        i += 1
        while i < len(lines):
            item = re.match(r"^(\s+)-\s+(\S.*)$", lines[i])
            if not item or len(item.group(1)) <= indent:
                break
            found.append(item.group(2).strip().strip("\"'"))
            i += 1
    return tuple(dict.fromkeys(found))
