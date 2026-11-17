from bugfix_contracts.repair import Feedback, InputRevision
from bugfix_platform.agents.analyst.revisions import merge_revision
import pytest

def test_merge_preserves_target_and_steps():
    parent = InputRevision(revisionId="v0", defectId="D", expected="remove switch", steps="open", attachments=["a"])
    rev = merge_revision(parent, Feedback(feedbackId="f", defectId="D", text="hook is broken", attachments=["b"]))
    assert rev.expected == "remove switch" and rev.steps == "open"
    assert rev.feedbackText == "hook is broken"
    assert rev.attachments == ["a", "b"]
    assert rev.parentRevisionId == "v0"

def test_clear_and_remove_are_explicit():
    parent = InputRevision(revisionId="v0", defectId="D", expected="old", attachments=["a"])
    rev = merge_revision(parent, Feedback(feedbackId="f", defectId="D", clearFields=["expected"], removeAttachmentIds=["a"]))
    assert rev.expected is None and rev.attachments == []

def test_wrong_parent_rejected():
    with pytest.raises(ValueError, match="parent"):
        merge_revision(InputRevision(revisionId="v0", defectId="D"), Feedback(feedbackId="f", defectId="D", parentRevisionId="wrong"))


def test_resume_execute_flag_reaches_command(monkeypatch):
    from bugfix_platform import cli
    captured = {}
    def fake(root, defect_id, revision_id, apply_fix=False, execute=False):
        captured.update(execute=execute, apply_fix=apply_fix)
        return 0
    monkeypatch.setattr(cli, "_cmd_resume", fake)
    assert cli.main(["resume", "--root", "unused", "--defect-id", "D", "--execute"]) == 0
    assert captured == {"execute": True, "apply_fix": False}


def test_latest_revision_uses_import_order_not_feedback_id(tmp_path):
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from bugfix_platform.agents.analyst.sessions import load_revision
    first=import_feedback(tmp_path,Feedback(feedbackId='z-first',defectId='D',text='fact one',expected='remove switch',steps='open settings'))
    second=import_feedback(tmp_path,Feedback(feedbackId='a-second',defectId='D',text='fact two',parentRevisionId=first.revisionId))
    assert load_revision(tmp_path,'D').revisionId==second.revisionId
    assert second.expected=='remove switch' and second.steps=='open settings'
    assert 'fact one' in second.feedbackText and 'fact two' in second.feedbackText
    with pytest.raises(ValueError,match='unknown revision'): load_revision(tmp_path,'D','missing')
    with pytest.raises(ValueError,match='conflicts'): import_feedback(tmp_path,Feedback(feedbackId='z-first',defectId='D',text='different'))


def test_missing_latest_parent_is_not_silently_reset(tmp_path):
    import json
    from bugfix_platform.agents.analyst.feedback import import_feedback
    from bugfix_platform.agents.analyst.sessions import load_revision
    with pytest.raises(ValueError,match='unknown revision'): load_revision(tmp_path,'D','unknown')
    folder=tmp_path/'defects'/'D';(folder/'feedback').mkdir(parents=True)
    (folder/'feedback-latest.json').write_text(json.dumps({'revisionId':'lost'}))
    with pytest.raises(ValueError,match='unknown revision'):
        import_feedback(tmp_path,Feedback(feedbackId='new',defectId='D',text='new facts'))
