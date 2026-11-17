from bugfix_agent1.defect_batch.distill import distill_defect
from bugfix_agent1.defect_batch.rules import match_vague
from bugfix_agent1.defect_batch.review import apply_intent_review
from bugfix_agent1.defect_batch.source_quality import assess_input_quality, build_source_document
from bugfix_contracts.defect_batch import RawDefect, DefectBatch


def test_missing_error_message_is_concrete_investigable_behavior():
    digest=distill_defect(RawDefect(defectId='D',title='保存失败但没有错误提示',description='操作步骤：保存配置\n实际结果：失败但没有错误提示\n预期结果：显示失败原因'))
    assert match_vague(digest) is None


def test_ranking_direction_not_rejected_as_vague():
    digest=distill_defect(RawDefect(defectId='D',title='排行显示异常，顺序相反',description='实际结果：bottom 项排在 top 项前面\n预期结果：按排名升序'))
    assert match_vague(digest) is None


def test_semantic_review_can_record_conflict_without_replacing_original():
    source=build_source_document(RawDefect(defectId='D',title='D',description='原始问题：按钮状态错误'))
    batch=DefectBatch.model_validate({'schemaVersion':'0.3.0','productLine':'p','posture':'alpha','generatedAt':'2026-01-01T00:00:00Z',
        'funnel':{'total':1,'needsInfo':1},'clusters':[],'tickets':[{'defectId':'D','title':'D','pool':'needs_info','expectQuality':'ambiguous','sourceDocument':source.model_dump()}]})
    updated=apply_intent_review(batch,[{'defectId':'D','inputQuality':{'expectedOrigin':'explicit','expectedRelevance':'conflicting','issues':['unrelated case expectation']}}])
    assert updated.tickets[0].inputQuality.expectedRelevance=='conflicting'
    assert updated.tickets[0].sourceDocument==source
    assert updated.tickets[0].pool=='needs_info'


def test_ranking_label_alone_is_not_a_concrete_comparison():
    digest=distill_defect(RawDefect(defectId='D',title='排行榜显示异常',
        description='实际结果：排行榜显示异常\n预期结果：应正常显示'))
    hit=match_vague(digest)
    assert hit is not None and hit.id=='C1c'
