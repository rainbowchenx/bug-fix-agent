"""Structural claim checks, deliberately not a semantic truth oracle."""
from bugfix_contracts.repair import Claim, Question

def normalize_root(root: dict) -> dict:
    data=dict(root)
    if data.get('questions') is not None:
        questions=[Question.model_validate(q) for q in data['questions']]
        data['questions']=[q.model_dump() for q in questions]
        data['openQuestions']=[q.reason for q in questions]
    claims=[Claim.model_validate(c) for c in data.get('claims',[])]
    for claim in claims:
        if claim.status=='supported' and (not claim.evidenceRefs or claim.assumptions):
            claim.status='conditional' if claim.assumptions else 'unverified'
    ids=[c.claimId for c in claims]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate claimId')
    for question in data.get('questions') or []:
        if not set(question['relatedClaimIds']).issubset(ids):
            raise ValueError('question references unknown claim')
    if claims and not any(c.status == 'supported' and c.role == 'conclusion' for c in claims):
        summary=data.get('summary') or ''
        data['summary']=('[Conditional / unverified] ' + summary if not summary.startswith('[Conditional / unverified]') else summary) if summary else summary
    if 'claims' in data:
        data['claims']=[c.model_dump() for c in claims]
    return data


def evidence_aliases(evidence, candidates, defect_id):
    """Map model candidate:N / path aliases onto this attempt's valid evidence IDs."""
    valid={e.evidenceId for e in evidence if getattr(e, "validity", None) == "valid"}
    aliases={}
    for i, candidate in enumerate(candidates, 1):
        eid=f'read-{defect_id}-{i}'
        if eid in valid:
            aliases[f'candidate:{i}']=eid
            path = candidate.get("path") if isinstance(candidate, dict) else getattr(candidate, "path", None)
            if path:
                aliases[str(path)]=eid
    return aliases, valid


def bind_claims(root, evidence, candidates, defect_id, *, drifted=False):
    """Resolve references against this attempt's checked code, without claiming causality."""
    data=dict(root)
    aliases, valid = evidence_aliases(evidence, candidates, defect_id)
    if 'claims' in data:
        claims=[]
        for raw in data.get('claims') or []:
            claim=Claim.model_validate(raw)
            refs=[aliases.get(ref,ref) for ref in claim.evidenceRefs]
            if claim.status == 'supported' and (drifted or not refs or any(ref not in valid for ref in refs)):
                claim.status='unverified'
            claim.evidenceRefs=refs
            claims.append(claim.model_dump())
        data['claims']=claims
    if 'questions' in data:
        questions=[]
        for raw in data.get('questions') or []:
            question=Question.model_validate(raw)
            refs=[aliases.get(ref,ref) for ref in (question.newEvidenceRefs or [])]
            questions.append(question.model_copy(update={"newEvidenceRefs": refs}).model_dump())
        data['questions']=questions
    return normalize_root(data)
