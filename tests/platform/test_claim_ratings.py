from bugfix_platform.agents.analyst.ratings import RatingBinding, report_digest, rating_stale

def test_changed_claim_invalidates_rating():
    report={'claim':'old'}
    rating=RatingBinding(product='p',defectId='D',reportDigest=report_digest(report))
    assert not rating_stale(rating,report)
    assert rating_stale(rating,{'claim':'new'})

def test_stale_rating_excluded_and_alternatives_separate():
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
    from eval_agent3 import score_report
    report={'schemaVersion':'0.3.0','productLine':'p','workDir':'repo','generatedAt':'2026-01-01T00:00:00Z',
        'openMr':False,'applyFix':False,'summary':{'total':1,'byOutcome':{'plan_only':1}},'tickets':[
        {'defectId':'D','ticket':{'title':'t','pool':'strict'},'outcome':'plan_only','proposedFix':{'summary':'correct arguments'},'confidence':'low',
         'localization':{'candidates':[{'path':'alternative/f.ts','why':'read'}],'notes':'analyze=sdk'},
         'rootCause':{'summary':'conditional hypothesis','claims':[],'questions':[]},'suggestedVerify':{'executed':False}}]}
    case={'defectId':'D','expectPathPrefix':'primary','expectPathPrefixAlt':['alternative'],'accepted':True,'resolved':True,
        'ratingBinding':{'product':'p','defectId':'D','reportDigest':'outdated'}}
    scored=score_report(report,[case]); row=scored['rows'][0]
    assert row['ratingStatus']=='stale' and row['locAt3'] is None and row['staleScores']['locAt3WithAlternatives']
    assert scored['summary']['repair']['successRate'] is None
    case['ratingBinding']['reportDigest']=report_digest(report)
    assert score_report(report,[case])['rows'][0]['ratingStatus']=='bound'


def test_honest_failed_analysis_does_not_credit_inherited_localization():
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'packaging'))
    from eval_agent3 import score_ticket
    row=score_ticket({'defectId':'D','expectPathPrefix':'src','expectOutcomes':['plan_only']},
        {'defectId':'D','outcome':'other_blocked','analysisStatus':'incomplete',
         'localization':{'notes':'analyze=sdk_fallback; model modality configuration mismatch','candidates':[{'path':'src/a.ts'}]}})
    assert row['locAt3']  # raw directory coverage remains comparable
    assert row['inheritedLocalizationOnly'] and not row['completedAnalysisLocAt3']
    assert row['g0Pass'] and row['executionIssues']
