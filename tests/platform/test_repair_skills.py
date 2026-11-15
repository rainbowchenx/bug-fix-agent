"""T09：selected 不等于 applied；长正文与同名多仓不丢。"""

from pathlib import Path

from bugfix_contracts.code_knowledge import RepoRoot
from bugfix_platform.agents.analyst.context import skill_usage_from_injected
from bugfix_platform.sdk.skill_inject import (
    InjectedSkill,
    analyze_skills_addon,
    discover_analyze_skills,
)


def test_selected_is_not_applied():
    skill = InjectedSkill(
        name="vue-debug",
        source="package",
        skill_md=Path("."),
        description="vue debug",
        profiles=("analyze",),
        body="# vue\n\n1. read\n2. fix\n",
    )
    usage = skill_usage_from_injected(skill, selected=True)
    assert usage.selected is True
    assert usage.applied is False


def test_overlay_body_keeps_late_steps(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    skill_dir = work / ".bugfix" / "skills" / "long-sop"
    skill_dir.mkdir(parents=True)
    marker = "CRITICAL-LATE-STEP-do-not-drop"
    body = ("前置说明\n" + ("x" * 2600) + f"\n{marker}\n")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: long-sop\ndescription: long\nprofiles: analyze\n---\n\n" + body,
        encoding="utf-8",
    )
    skills = discover_analyze_skills(work)
    text = analyze_skills_addon(skills)
    assert marker in text


def test_multiline_yaml_description(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    skill_dir = work / ".bugfix" / "skills" / "yaml-sop"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: yaml-sop\n"
        "description: |\n"
        "  line one\n"
        "  line two is important\n"
        "profiles: analyze\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    skills = [s for s in discover_analyze_skills(work) if s.name == "yaml-sop"]
    assert skills
    assert "line two is important" in skills[0].description


def test_same_name_skills_from_two_repos_are_kept(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "root"
    web = work / "web" / ".claude" / "skills" / "vue-debug"
    elec = work / "electron" / ".claude" / "skills" / "vue-debug"
    web.mkdir(parents=True)
    elec.mkdir(parents=True)
    (web / "SKILL.md").write_text(
        "---\nname: vue-debug\ndescription: web\nprofiles: analyze\n---\n\nweb-only-step\n",
        encoding="utf-8",
    )
    (elec / "SKILL.md").write_text(
        "---\nname: vue-debug\ndescription: electron\nprofiles: analyze\n---\n\nelectron-only-step\n",
        encoding="utf-8",
    )
    skills = discover_analyze_skills(
        work,
        repo_roots=[RepoRoot(path="web"), RepoRoot(path="electron")],
    )
    overlay = [s for s in skills if s.name == "vue-debug" and s.source == "claude_dir"]
    bodies = "\n".join(s.body for s in overlay)
    assert len(overlay) == 2
    assert "web-only-step" in bodies
    assert "electron-only-step" in bodies
