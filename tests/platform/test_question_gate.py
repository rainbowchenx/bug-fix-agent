from bugfix_contracts.repair import Question, EditDecision, TaskContext, Evidence
from bugfix_platform.agents.analyst.evidence import validate_edit_decision

def test_followup_does_not_block_but_blocking_does():
    ctx=TaskContext(defectId='D',evidence=[Evidence(evidenceId='e',category='code_observation',validity='valid')])
    d=EditDecision(behaviorTarget='correct',codeAssociation='a',mechanism='wrong argument',editRationale='swap',evidenceRefs=['e'],questions=[Question(id='q',kind='follow_up',reason='other button')])
    assert validate_edit_decision(ctx,d)==[]
    d.questions[0].kind='blocking'
    assert 'blocking question unresolved' in validate_edit_decision(ctx,d)
