"""Cartography skill injection merge + profile filter."""

from __future__ import annotations

from pathlib import Path

from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_contracts.defect_batch import DefectBatch
from bugfix_platform.sdk.skill_inject import (
    discover_cartography_skills,
    cartography_skills_addon,
)


def _write_skill(folder: Path, name: str, *, profiles: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: guide for {name}\nprofiles: {profiles}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-01-01T00:00:00Z",
            "funnel": {"total": 1, "strict": 1},
            "clusters": [],
            "tickets": [
                {
                    "defectId": "D1",
                    "title": "[回放] preview",
                    "pool": "strict",
                    "expectQuality": "explicit",
                    "testModule": "回放",
                    "titleTag": "回放",
                    "intent": "ui_layout",
                }
            ],
        }
    )


def test_bugfix_skills_override_package_and_skip_other_profiles(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".bugfix" / "skills" / "code-cartography",
        "code-cartography",
        profiles="cartography",
        body="先看 packages/player，不要扫 packages/legacy。",
    )
    _write_skill(
        work / ".bugfix" / "skills" / "gitlab-hygiene",
        "gitlab-hygiene",
        profiles="fix",
        body="这不该进 Agent-2。",
    )
    skills = discover_cartography_skills(work)
    names = {s.name: s for s in skills}
    assert names["code-cartography"].source == "bugfix"
    assert "先看 packages/player" in names["code-cartography"].body
    assert "gitlab-hygiene" not in names


def test_explicit_dir_overrides_bugfix(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    extra = tmp_path / "line-skills"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".bugfix" / "skills" / "hc-layout",
        "hc-layout",
        profiles="cartography",
        body="bugfix copy",
    )
    _write_skill(
        extra / "hc-layout",
        "hc-layout",
        profiles="cartography",
        body="line copy: 测试模块 回放 → packages/playback",
    )
    skills = discover_cartography_skills(work, extra_dirs=[extra])
    hit = next(s for s in skills if s.name == "hc-layout")
    assert hit.source == "explicit"
    assert "packages/playback" in hit.body


def test_addon_includes_injected_body_not_just_name(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        work / ".claude" / "skills" / "hc-read",
        "hc-read",
        profiles="cartography",
        body="单元测试在 tests/unit，e2e 不要当定位目标。",
    )
    skills = discover_cartography_skills(work)
    text = cartography_skills_addon(skills)
    assert "hc-read" in text
    assert "tests/unit" in text
    assert "never invent paths" in text
    assert "HIGHEST PRIORITY" in text
    overlay_at = text.find("hc-read")
    package_at = text.find("Package SOP")
    assert overlay_at != -1 and package_at != -1 and overlay_at < package_at
    names = [s.name for s in skills]
    assert names.index("hc-read") < names.index("code-cartography")


def test_metadata_profiles_counts_as_cartography(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = tmp_path / "repo"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    folder = work / ".bugfix" / "skills" / "hc-read"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: hc-read\ndescription: read this repo\n"
        "metadata:\n  profiles: cartography\n---\n\n先看 packages/player。\n",
        encoding="utf-8",
    )
    skills = discover_cartography_skills(work)
    assert any(s.name == "hc-read" for s in skills)


def test_env_skills_dir_is_merged(tmp_path: Path, monkeypatch):
    work = tmp_path / "repo"
    extra = tmp_path / "from-env"
    work.mkdir()
    (work / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    _write_skill(
        extra / "env-layout",
        "env-layout",
        profiles="cartography",
        body="env copy",
    )
    monkeypatch.setenv("BUGFIX_SKILLS_DIR", str(extra))
    skills = discover_cartography_skills(work)
    assert any(s.name == "env-layout" and s.source == "explicit" for s in skills)


def test_run_cartographer_records_injected_bound_skills(tmp_path: Path, monkeypatch):
    from tests.helpers import ensure_git_repo

    monkeypatch.delenv("BUGFIX_SKILLS_DIR", raising=False)
    work = ensure_git_repo(tmp_path / "repo")
    extra = tmp_path / "injected"
    (work / "package.json").write_text(
        '{"name":"x","dependencies":{"electron":"1"}}', encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "preview.ts").write_text("export {}\n", encoding="utf-8")
    _write_skill(
        extra / "hc-electron",
        "hc-electron",
        profiles="cartography",
        body="崩溃看 main，文案看 renderer。",
    )
    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=_batch(),
        cartography_mode="heuristic",
        extra_skill_dirs=[extra],
    )
    assert "hc-electron" in knowledge.boundSkills
    assert "code-cartography" in knowledge.boundSkills
    assert any(
        e.kind == "skill" and "hc-electron" in e.path for e in knowledge.specAtlas.entries
    )
    assert knowledge.boundSkills.index("hc-electron") < knowledge.boundSkills.index(
        "code-cartography"
    )
