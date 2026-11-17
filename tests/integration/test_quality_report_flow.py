"""Real entry/control chain with injected analysis; this does not certify model semantics."""
import json
from bugfix_agent1.defect_batch.run import run_defect_batch_prepare
from bugfix_platform.agents.cartographer import run_cartographer
from bugfix_platform.agents.analyst import run_analyst
from bugfix_platform.cli import main
from bugfix_platform.sdk.analyze import AnalyzeResult, _build_prompt


def test_original_ticket_through_feedback_and_report_only_resume(tmp_path,monkeypatch):
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    from tests.helpers import ensure_git_repo
    work=ensure_git_repo(tmp_path/'repo')
    code=work/'switch.ts'; code.write_text('export const showSwitch = true;\n')
    (work/'.env').write_text('TEST_ONLY=dummy\n')
    raw='前置条件：设备在线\n测试数据：90°\n操作步骤：打开设置\n实际结果：仍显示开关\n预期结果：移除开关\n问题：https://example.test/replay'
    batch=run_defect_batch_prepare(product_line='p',posture='alpha',source=[{
        'defectId':'D','title':'设置中需要移除开关','description':raw,'测试环境':'Windows','产品型号':'M'}])
    assert batch.tickets[0].sourceDocument.description==raw
    assert batch.tickets[0].sourceDocument.fields['测试环境']=='Windows'
    knowledge=run_cartographer(work_dir=work,defect_batch=batch,cartography_mode='heuristic')
    calls=[]
    def analyze(req):
        calls.append(_build_prompt(req))
        return AnalyzeResult(True,{'outcome':'plan_only','rootCause':{'summary':'mechanism remains conditional','claims':[],
            'questions':[{'id':'q','kind':'verification','reason':'device acceptance'}],'openQuestions':['device acceptance']},
            'proposedFix':{'summary':'honor removal target','targetFiles':['switch.ts'],'steps':['remove toggle']},
            'localization':{'candidates':[]}},'sdk')
    def forbidden(*a,**kw): raise AssertionError('report-only flow called editor')
    monkeypatch.setattr('bugfix_platform.agents.analyst.run.create_analyze_runner',lambda *a,**kw:analyze)
    monkeypatch.setattr('bugfix_platform.agents.analyst.run.create_fix_runner',forbidden)
    out=tmp_path/'out';out.mkdir()
    first=run_analyst(work_dir=work,defect_batch=batch,code_knowledge=knowledge,apply_fix=False,artifact_dir=out)
    (out/'defect-batch.json').write_text(batch.model_dump_json(),encoding="utf-8")
    (out/'code-knowledge.json').write_text(knowledge.model_dump_json(),encoding="utf-8")
    (out/'analysis-report.json').write_text(first.model_dump_json(),encoding="utf-8")
    feedback=tmp_path/'feedback.json';feedback.write_text(json.dumps({'feedbackId':'z-first','defectId':'D',
        'kind':'change_expected','expected':'移除开关','text':'确认移除开关，弹窗问题另行处理'},ensure_ascii=False),encoding='utf-8')
    assert main(['feedback','--root',str(out),'--file',str(feedback)])==0
    assert main(['resume','--root',str(out),'--defect-id','D','--execute'])==0
    assert len(calls)==2 and '确认移除开关' in calls[-1] and '移除开关' in calls[-1]
    assert 'https://example.test/replay' in calls[-1]
    result=json.loads((out/'analysis-report.json').read_text(encoding='utf-8'))
    assert result['applyFix'] is False
    assert result['tickets'][0]['ticket']['sourceDocument']['description']==raw
    assert result['tickets'][0]['rootCause']['questions'][0]['kind']=='verification'
    assert list((out/'rounds').glob('*.json'))
    assert code.read_text()=='export const showSwitch = true;\n'


def test_needs_info_receives_bounded_first_investigation(tmp_path,monkeypatch):
    from bugfix_contracts import DefectBatch,CodeKnowledge
    monkeypatch.setenv('BUGFIX_CODEGRAPH','0')
    batch=DefectBatch.model_validate({'schemaVersion':'0.3.0','productLine':'p','posture':'alpha','generatedAt':'2026-01-01T00:00:00Z',
        'funnel':{'total':1,'needsInfo':1},'clusters':[],'tickets':[{'defectId':'D','title':'UI missing hint','pool':'needs_info','expectQuality':'absent'}]})
    knowledge=CodeKnowledge.model_validate({'schemaVersion':'0.3.0','productLine':'p','workDir':str(tmp_path),'partial':False,'generatedAt':'2026-01-01T00:00:00Z'})
    seen=[]
    def analyze(req):
        seen.append(req)
        return AnalyzeResult(True,{**req.routed,'rootCause':{'summary':'need screenshot','claims':[],'questions':[{'id':'q','kind':'blocking','reason':'need screenshot'}]}},'sdk')
    report=run_analyst(work_dir=tmp_path,defect_batch=batch,code_knowledge=knowledge,analyze_fn=analyze,apply_fix=False)
    assert len(seen)==1 and seen[0].max_turns==8
    assert report.tickets[0].outcome=='needs_ticket_info'
