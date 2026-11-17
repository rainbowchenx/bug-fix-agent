import json
from pathlib import Path
import pytest
from bugfix_contracts.defect_batch import DefectBatch
from bugfix_contracts.repair import Claim, Question


def test_quality_contract_round_trip_and_old_version_rejected():
    payload={'schemaVersion':'0.4.0','productLine':'p','posture':'alpha','generatedAt':'2026-01-01T00:00:00Z',
        'funnel':{'total':0},'clusters':[],'tickets':[]}
    batch=DefectBatch.model_validate(payload)
    assert DefectBatch.model_validate_json(batch.model_dump_json())==batch
    with pytest.raises(ValueError): DefectBatch.model_validate({**payload,'schemaVersion':'0.1.0'})
    claim=Claim(claimId='c',statement='conditional mechanism',role='hypothesis',status='conditional',assumptions=['device state'])
    assert Claim.model_validate_json(claim.model_dump_json())==claim
    q=Question(id='q',kind='blocking',reason='missing device state',relatedClaimIds=['c'])
    assert Question.model_validate_json(q.model_dump_json())==q
