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
    return InputRevision.model_validate(data)
