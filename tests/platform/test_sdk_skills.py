from bugfix_platform.sdk.skills import list_package_skill_names, package_skills_root, skills_system_addon


def test_package_skills_listed():
    root = package_skills_root()
    assert root.is_dir()
    names = list_package_skill_names()
    assert "hierarchical-localization" in names
    assert "systematic-debugging" in names
    assert "code-cartography" in names
    assert "defect-batch-prepare" not in names


def test_skills_system_addon_mentions_paths():
    text = skills_system_addon(("hierarchical-localization",))
    assert "hierarchical-localization" in text
    assert "SKILL.md" in text
