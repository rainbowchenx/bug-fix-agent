from dataclasses import replace
import pytest
from bugfix_contracts import DefectBatch, CodeKnowledge
from bugfix_platform.agents.cartographer.investigation import plan_groups, investigate_groups
from bugfix_platform.sdk.cartography import CartographyRequest, CartographyResult


def request(tmp_path, n=37):
    batch=DefectBatch.model_validate({'schemaVersion':'0.4.0','productLine':'p','posture':'alpha',
        'generatedAt':'2026-01-01T00:00:00Z','funnel':{'total':n,'strict':n},'clusters':[],
        'tickets':[{'defectId':str(i),'title':'failure','pool':'strict','expectQuality':'explicit'} for i in range(n)]})
    knowledge=CodeKnowledge.model_validate({'schemaVersion':'0.4.0','productLine':'p','workDir':str(tmp_path),
        'generatedAt':'2026-01-01T00:00:00Z','partial':False,
        'defectCodeMatches':[{'defectId':str(i),'candidates':[],'confidence':'low'} for i in range(n)]})
    return CartographyRequest(str(tmp_path),batch,knowledge)


def complete(req):
    matches=[m.model_copy(update={'investigationStatus':'complete','searchedScopes':['src']}) for m in req.baseline.defectCodeMatches]
    return CartographyResult(True,req.baseline.model_copy(update={'partial':False,'defectCodeMatches':matches}),'sdk')


def test_stable_groups_include_seventeenth_ticket():
    ids=[str(i) for i in range(37)]
    assert [x for g in plan_groups(ids) for x in g]==ids
    with pytest.raises(ValueError): plan_groups(ids,0)


def test_all_groups_run_once_and_completed_cache_reused(tmp_path):
    req=request(tmp_path/'repo'); calls=[]
    def runner(r):
        calls.append(r)
        return complete(r)
    cache=tmp_path/'cache'
    result=investigate_groups(req,runner,cache_dir=cache)
    assert len(calls)==5 and len(result.knowledge.defectCodeMatches)==37
    assert not result.knowledge.partial
    assert not calls[0].investigation_only and all(r.investigation_only for r in calls[1:])
    investigate_groups(req,runner,cache_dir=cache)
    assert len(calls)==5
    (tmp_path/'repo').mkdir(exist_ok=True)
    (tmp_path/'repo'/'changed.ts').write_text('changed')
    investigate_groups(req,runner,cache_dir=cache)
    assert len(calls)==10


def test_budget_stops_before_new_group(tmp_path):
    result=investigate_groups(request(tmp_path),complete,max_groups=1)
    statuses=[m.investigationStatus for m in result.knowledge.defectCodeMatches]
    assert statuses.count('complete')==8 and statuses.count('not_investigated')==29
    assert result.knowledge.partial


def test_failed_group_is_retried_without_losing_cached_groups(tmp_path):
    req=request(tmp_path/'repo',17); calls=[]
    def runner(r):
        ids=[t.defectId for t in r.defect_batch.tickets]; calls.append(ids)
        if ids[0]=='8' and len(calls)==2: raise RuntimeError('provider timeout')
        return complete(r)
    first=investigate_groups(req,runner,cache_dir=tmp_path/'cache')
    assert sum(m.investigationStatus=='failed' for m in first.knowledge.defectCodeMatches)==8
    second=investigate_groups(req,runner,cache_dir=tmp_path/'cache')
    assert calls[-1][0]=='8' and len(calls)==4
    assert not second.knowledge.partial


def test_foreign_ticket_rejected(tmp_path):
    def runner(req):
        result=complete(req)
        result.knowledge.defectCodeMatches[0].defectId='foreign'
        return result
    result=investigate_groups(request(tmp_path,1),runner)
    assert result.knowledge.defectCodeMatches[0].defectId=='0'
    assert result.knowledge.defectCodeMatches[0].investigationStatus=='failed'


def test_budget_resume_skips_cached_groups_and_advances(tmp_path):
    req=request(tmp_path/'repo',17); cache=tmp_path/'cache';calls=[]
    def runner(r): calls.append(r);return complete(r)
    first=investigate_groups(req,runner,max_groups=1,cache_dir=cache)
    second=investigate_groups(req,runner,max_groups=1,cache_dir=cache)
    assert sum(m.investigationStatus=='complete' for m in first.knowledge.defectCodeMatches)==8
    assert sum(m.investigationStatus=='complete' for m in second.knowledge.defectCodeMatches)==16
    assert len(calls)==2


def test_budget_config_change_invalidates_cache(tmp_path,monkeypatch):
    req=request(tmp_path/'repo',1);cache=tmp_path/'cache';calls=[]
    def runner(r): calls.append(r);return complete(r)
    monkeypatch.setenv('BUGFIX_CARTOGRAPHY_MAX_TURNS','4')
    investigate_groups(req,runner,cache_dir=cache)
    monkeypatch.setenv('BUGFIX_CARTOGRAPHY_MAX_TURNS','20')
    investigate_groups(req,runner,cache_dir=cache)
    assert len(calls)==2


def test_formal_cartographer_entry_dispatches_all_ticket_groups(tmp_path,monkeypatch):
    from tests.helpers import ensure_git_repo
    from bugfix_platform.agents.cartographer import run_cartographer
    from bugfix_platform.sdk.codegraph import CodeGraphStatus
    ensure_git_repo(tmp_path)
    monkeypatch.setattr('bugfix_platform.agents.cartographer.run.ensure_codegraph',lambda *a,**kw:CodeGraphStatus(ready=False))
    calls=[]
    def runner(req):
        calls.extend(t.defectId for t in req.defect_batch.tickets)
        return complete(req)
    monkeypatch.setattr('bugfix_platform.agents.cartographer.run.create_cartography_runner',lambda *a:runner)
    knowledge=run_cartographer(work_dir=tmp_path,defect_batch=request(tmp_path,37).defect_batch,cartography_mode='sdk')
    assert calls==[str(i) for i in range(37)]
    assert len(knowledge.investigationRuns)==5
    assert len(knowledge.defectCodeMatches)==37 and not knowledge.partial
