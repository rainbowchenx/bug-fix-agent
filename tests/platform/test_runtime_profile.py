from bugfix_platform.sdk.runtime_profile import runtime_profile, modality_error

def test_declared_large_window_is_not_verified(monkeypatch):
    monkeypatch.setenv('BUGFIX_MODEL_CONTEXT_WINDOW','1000000')
    monkeypatch.setenv('BUGFIX_MODEL_MODALITIES','text,image')
    p=runtime_profile()
    assert p.contextWindow==1000000 and p.capabilityStatus=='declared'
    assert modality_error('The current model only supports text modality and does not support image input')


def test_allowlist_selects_unprofiled_skill_without_claiming_applied(tmp_path,monkeypatch):
    from bugfix_platform.sdk.skill_inject import discover_analyze_skills
    from bugfix_platform.sdk.runtime_profile import skill_discovery
    from bugfix_contracts.code_knowledge import RepoRoot
    skill=tmp_path/'.claude'/'skills'/'business';skill.mkdir(parents=True)
    (skill/'SKILL.md').write_text('---\nname: business\ndescription: verification rules\n---\nRead local setup.')
    roots=[RepoRoot(path='.')]
    not_selected=skill_discovery(str(tmp_path),roots,[])
    assert not_selected[0]['selected'] is False and not_selected[0]['reason']
    monkeypatch.setenv('BUGFIX_SKILL_ALLOWLIST','business')
    selected=discover_analyze_skills(tmp_path,repo_roots=roots)
    business=next(s for s in selected if s.name=='business')
    rows=skill_discovery(str(tmp_path),roots,selected,[str(business.skill_md.resolve())])
    row=next(r for r in rows if r['path']==str(business.skill_md) or r['path']==str(business.skill_md.resolve()))
    assert row['selected'] and row['read'] and row['applied'] is False
