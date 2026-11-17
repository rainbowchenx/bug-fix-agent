from bugfix_platform.agents.analyst.claims import normalize_root

def test_unobserved_assumption_not_promoted_by_valid_quote():
    root=normalize_root({'summary':'candidate','questions':[{'id':'q','kind':'verification','reason':'need device logs'}],
      'claims':[{'claimId':'c','statement':'init resets device red','role':'conclusion','status':'supported','evidenceRefs':['candidate:1'],'assumptions':['device returns red after init']}]})
    assert root['claims'][0]['status']=='conditional'
    assert root['openQuestions']==['need device logs']

def test_static_supported_claim_can_remain_supported():
    root=normalize_root({'claims':[{'claimId':'c','statement':'arguments reversed','role':'fact','status':'supported','evidenceRefs':['candidate:1']}]})
    assert root['claims'][0]['status']=='supported'


def test_missing_claims_not_silently_defaulted_before_sdk_gate():
    from bugfix_platform.sdk.analyze import parse_analyze_payload
    assert 'claims' not in parse_analyze_payload({'rootCause':{'summary':'incomplete','questions':[]}})['rootCause']


def test_forged_claim_reference_not_supported():
    from bugfix_platform.sdk.analyze import parse_analyze_payload
    parsed=parse_analyze_payload({'rootCause':{'summary':'definitely fixed','questions':[],
        'claims':[{'claimId':'c','statement':'cause','role':'conclusion','status':'supported','evidenceRefs':['nonexistent']}]}})
    assert parsed['rootCause']['claims'][0]['status']=='unverified'
    assert parsed['rootCause']['summary'].startswith('[Conditional')


def test_reference_must_resolve_to_current_valid_code():
    from bugfix_platform.agents.analyst.claims import bind_claims
    from bugfix_contracts.repair import Evidence
    root={'summary':'swap args','claims':[{'claimId':'c','statement':'args reversed','role':'conclusion','status':'supported','evidenceRefs':['candidate:1']}]}
    evidence=[Evidence(evidenceId='read-D-1',category='code_observation',validity='valid')]
    assert bind_claims(root,evidence,[{'path':'a.ts'}],'D')['claims'][0]['status']=='supported'
    assert bind_claims(root,evidence,[{'path':'a.ts'}],'D',drifted=True)['claims'][0]['status']=='unverified'
    assert bind_claims(root,[],[{'path':'a.ts'}],'D')['claims'][0]['status']=='unverified'
