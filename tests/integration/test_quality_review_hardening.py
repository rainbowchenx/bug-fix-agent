"""Entry-point regressions found during the 2026-11-17 implementation review."""
import json
import pytest
from fastapi.testclient import TestClient
from tests.helpers import ensure_git_repo, minimal_defect_batch
from tests.platform.test_repair_entry import _knowledge
from tests.platform.test_investigation_batches import request
from bugfix_platform.http import create_app
from bugfix_platform.workflow import run_three_agent_workflow
from bugfix_platform.agents.cartographer.handoff import _merge_enrichment


@pytest.mark.parametrize('options',[{}, {'applyFix':False}])
def test_http_report_only_overrides_fix_environment(tmp_path,monkeypatch,options):
    monkeypatch.setenv('BUGFIX_APPLY_FIX','1')
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append(True)
        raise AssertionError('HTTP report mode instantiated editor')
    monkeypatch.setattr('bugfix_platform.agents.analyst.run.create_fix_runner',forbidden)
    client=TestClient(create_app(background=False))
    work=ensure_git_repo(tmp_path/'repo')
    response=client.post('/v1/runs',json={'workDir':str(work),'productLine':'hc',
        'defectBatch':minimal_defect_batch().model_dump(),'options':{
            'analyzeMode':'heuristic','cartographyMode':'heuristic',**options}})
    assert response.status_code==202
    run=response.json()
    status=client.get('/v1/runs/'+run['runId'],params={'workDir':run['workDir']}).json()
    assert status['status']=='succeeded' and calls==[]
    from pathlib import Path
    report=json.loads(Path(status['artifacts']['analysisReportPath']).read_text(encoding='utf-8'))
    assert report['applyFix'] is False


def test_http_does_not_retry_internal_type_error(tmp_path):
    calls=[]
    def broken(**kwargs):
        calls.append(kwargs)
        raise TypeError('internal bug, not unsupported kwargs')
    client=TestClient(create_app(workflow_fn=broken,background=False))
    client.post('/v1/runs',json={'workDir':str(tmp_path),'productLine':'hc',
        'defectBatch':minimal_defect_batch().model_dump()})
    assert len(calls)==1


def test_graph_does_not_drop_authorization_and_repeat_internal_type_error(tmp_path):
    calls=[]
    def broken(**kwargs):
        calls.append(kwargs)
        raise TypeError('internal agent error')
    result=run_three_agent_workflow(work_dir=tmp_path,product_line='hc',defect_batch=minimal_defect_batch(),
        agent2=lambda **kwargs:_knowledge(tmp_path),agent3=broken,apply_fix=False)
    assert not result.ok and len(calls)==1
    assert calls[0]['apply_fix'] is False


@pytest.mark.parametrize('matches',[
    [{'defectId':'0','candidates':[]},{'defectId':'0','candidates':[]}],
    [{'defectId':'outside-group','candidates':[],'confidence':'INVALID'}],
])
def test_sdk_isolates_invalid_ticket_identity_before_merge(tmp_path,matches):
    req=request(tmp_path,1)
    merged=_merge_enrichment(req.baseline,{'defectCodeMatches':matches},tickets=req.defect_batch.tickets)
    ids={m['defectId'] for m in merged['defectCodeMatches']}
    assert 'outside-group' not in ids


def test_failed_ticket_report_keeps_effective_revision(tmp_path,monkeypatch):
    from tests.platform.test_repair_entry import _batch
    from bugfix_platform.agents.analyst import run_analyst
    from bugfix_contracts.repair import InputRevision
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    def broken(req): raise RuntimeError('provider unavailable')
    report=run_analyst(work_dir=tmp_path,defect_batch=_batch(),code_knowledge=_knowledge(tmp_path),
        revisions={'D1':InputRevision(revisionId='D1:new',defectId='D1',expected='remove switch')},
        analyze_fn=broken,apply_fix=False)
    ticket=report.tickets[0]
    assert ticket.outcome=='other_blocked'
    assert ticket.ticket.expected=='remove switch' and ticket.ticket.revisionId=='D1:new'


def test_successfully_read_attachment_is_not_still_an_edit_blocker(tmp_path,monkeypatch):
    from tests.platform.test_repair_entry import _batch
    from bugfix_platform.agents.analyst import run_analyst
    from bugfix_platform.sdk.analyze import AnalyzeResult
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'a.ts').write_text('export const showSwitch = true;')
    attachment=tmp_path/'screen.png';attachment.write_bytes(b'test fixture')
    batch=_batch();batch.tickets[0].attachmentRefs=['screen.png']
    def analyze(req):
        return AnalyzeResult(True,{'outcome':'plan_only','rootCause':{'summary':'screenshot code uses showSwitch','questions':[],'claims':[]},
            'proposedFix':{'summary':'remove showSwitch','targetFiles':['src/a.ts']},
            'localization':{'candidates':[{'path':'src/a.ts','symbol':'showSwitch','snippet':'export const showSwitch = true;'}]}},
            'sdk',read_paths=[str(attachment.resolve())])
    report=run_analyst(work_dir=tmp_path,defect_batch=batch,code_knowledge=_knowledge(tmp_path),analyze_fn=analyze,apply_fix=False)
    assert report.tickets[0].attachments[0]['read'] is True
    assert report.tickets[0].actionability['allowed'] is True


@pytest.mark.parametrize('read_failed',[False,True])
def test_agent2_successful_skill_read_reaches_formal_manifest(tmp_path,monkeypatch,read_failed):
    from types import SimpleNamespace
    import claude_agent_sdk
    from tests.platform.test_sdk_billing import _result
    from bugfix_platform.agents.cartographer import run_cartographer
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-key')
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    ensure_git_repo(tmp_path)
    skill=tmp_path/'.claude'/'skills'/'business'/'SKILL.md';skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: business\nprofiles: [cartography]\n---\nRead setup instructions.')
    async def query(*,prompt,options):
        yield SimpleNamespace(content=[SimpleNamespace(name='Read',id='r',input={'file_path':'.claude/skills/business/SKILL.md'})])
        yield SimpleNamespace(content=[SimpleNamespace(tool_use_id='r',is_error=read_failed,content='read response')])
        yield _result(structured_output={'partial':False,'defectCodeMatches':[{
            'defectId':'0','candidates':[],'confidence':'low','searchedScopes':['src']}]})
    monkeypatch.setattr(claude_agent_sdk,'query',query)
    knowledge=run_cartographer(work_dir=tmp_path,defect_batch=request(tmp_path,1).defect_batch,cartography_mode='sdk')
    row=next(r for r in knowledge.skillDiscovery if 'business' in r['path'])
    assert row['selected'] and row['read'] is (not read_failed)
    assert row['applied'] is False


def test_resume_unknown_defect_does_not_report_success(tmp_path,monkeypatch):
    from bugfix_platform.cli import main
    from tests.platform.test_repair_entry import _batch
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    (tmp_path/'defect-batch.json').write_text(_batch().model_dump_json(),encoding='utf-8')
    (tmp_path/'code-knowledge.json').write_text(_knowledge(tmp_path).model_dump_json(),encoding='utf-8')
    assert main(['resume','--root',str(tmp_path),'--defect-id','unknown','--execute'])==1
    assert not (tmp_path/'rounds').exists()


def test_feedback_unknown_defect_cannot_create_orphan_revision(tmp_path):
    from tests.platform.test_repair_entry import _batch
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from bugfix_contracts.repair import Feedback
    (tmp_path/'defect-batch.json').write_text(_batch().model_dump_json(),encoding='utf-8')
    with pytest.raises(ValueError,match='unknown defect'):
        import_feedback(tmp_path,Feedback(feedbackId='f',defectId='unknown',text='new details'))


def test_resume_rejects_old_report_before_analysis(tmp_path,monkeypatch):
    from bugfix_platform.cli import main
    from tests.platform.test_repair_entry import _batch
    from tests.platform.test_eval_agent3 import _report, _ticket
    (tmp_path/'defect-batch.json').write_text(_batch().model_dump_json(),encoding='utf-8')
    (tmp_path/'code-knowledge.json').write_text(_knowledge(tmp_path).model_dump_json(),encoding='utf-8')
    old=_report([_ticket()]);old['schemaVersion']='0.1.0'
    (tmp_path/'analysis-report.json').write_text(json.dumps(old),encoding='utf-8')
    def forbidden(**kwargs): raise AssertionError('old report was accepted for resume')
    monkeypatch.setattr('bugfix_platform.agents.analyst.run.run_analyst',forbidden)
    with pytest.raises(ValueError,match='schemaVersion'):
        main(['resume','--root',str(tmp_path),'--defect-id','D1','--execute'])
    assert not (tmp_path/'defects'/'D1'/'session-decision.json').exists()
