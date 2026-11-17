"""Merge feedback without replacing the effective ticket by a free-text note."""
from bugfix_contracts.repair import Feedback, InputRevision

def merge_revision(parent: InputRevision, feedback: Feedback) -> InputRevision:
    if parent.defectId != feedback.defectId:
        raise ValueError("feedback defect does not match parent")
    if feedback.parentRevisionId and feedback.parentRevisionId != parent.revisionId:
        raise ValueError("unknown parent revision")
    data = parent.model_dump()
    for key in ("observed", "expected", "steps"):
        value = getattr(feedback, key)
        if value is not None:
            data[key] = value
        if key in feedback.clearFields:
            data[key] = None
    data.update(revisionId=f"{feedback.defectId}:{feedback.feedbackId}",
                parentRevisionId=parent.revisionId, parentId=parent.revisionId,
                feedbackText="\n\n".join(x for x in [parent.feedbackText, feedback.text] if x), source="feedback")
    data["attachments"] = list(dict.fromkeys(
        x for x in parent.attachments + feedback.attachments
        if x not in feedback.removeAttachmentIds))
    answers = list(parent.questionAnswers or [])
    latest = {a.questionId: i for i, a in enumerate(answers)}
    for item in feedback.questionAnswers or []:
        payload = item.model_copy(update={"answerRevisionId": item.answerRevisionId or data["revisionId"]})
        if item.questionId in latest:
            answers[latest[item.questionId]] = payload
        else:
            latest[item.questionId] = len(answers)
            answers.append(payload)
    data["questionAnswers"] = [a.model_dump() if hasattr(a, "model_dump") else a for a in answers]
    return InputRevision.model_validate(data)
