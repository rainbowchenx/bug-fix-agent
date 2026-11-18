"""Structural claim checks, deliberately not a semantic truth oracle."""
from bugfix_contracts.analysis_report import normalize_root
from bugfix_contracts.repair import Claim, Question

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
