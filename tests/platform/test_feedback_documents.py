"""T6：用户只填答复区；绑定错误报 stale。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, InputRevision
from bugfix_platform.agents.analyst.analysis_store import build_snapshot_from_entry, save_analysis_snapshot
from bugfix_platform.agents.analyst.feedback import import_feedback
from bugfix_platform.agents.analyst.feedback_document import (
    FeedbackFormError,
    parse_feedback_form,
    render_feedback_form,
)
from bugfix_platform.cli import main as platform_main
from tests.platform.test_analysis_snapshots import _entry


def _saved_form(tmp_path: Path) -> tuple[Path, str]:
    attempt = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a1",
        defectId="D1",
        execution="completed",
        resolution="analysis_only",
    )
    snap = build_snapshot_from_entry(
        _entry(),
        revision=InputRevision(revisionId="D1:v0", defectId="D1"),
    )
    save_analysis_snapshot(tmp_path, attempt, snap)
    text = render_feedback_form(snap)
    return tmp_path, text


def test_user_fills_answer_region_without_json(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    filled = text.replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:q1 -->\nuse a+b\n<!-- /ANSWER:q1 -->",
    )
    feedback = parse_feedback_form(filled, store=root)
    assert feedback.questionAnswers[0].text == "use a+b"
    assert feedback.defectId == "D1"
    rev = import_feedback(root, feedback)
    assert rev.questionAnswers[0].text == "use a+b"


def test_blank_answers_do_not_clear_and_body_edits_are_ignored(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    edited = text.replace("summary: first round", "summary: HACKED")
    feedback = parse_feedback_form(edited, store=root)
    assert feedback.questionAnswers == []
    assert feedback.kind == "unknown"


def test_stale_digest_and_unknown_question_rejected(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    digest_line = next(line for line in text.splitlines() if line.startswith("digest:"))
    stale = text.replace(digest_line, "digest: " + "0" * 64)
    with pytest.raises(FeedbackFormError):
        parse_feedback_form(stale, store=root)
    unknown = text.replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:nope -->\nx\n<!-- /ANSWER:nope -->",
    )
    with pytest.raises(FeedbackFormError):
        parse_feedback_form(unknown, store=root)


def test_cli_imports_filled_markdown(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    filled = text.replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:q1 -->\nkeep current expected\n<!-- /ANSWER:q1 -->",
    )
    form = tmp_path / "filled.md"
    form.write_text(filled, encoding="utf-8")
    assert platform_main(["feedback", "--root", str(root), "--file", str(form)]) == 0


def test_second_attempt_makes_first_form_stale(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    a2 = AttemptRecord(
        schemaVersion=REPAIR_SCHEMA_VERSION,
        attemptId="a2",
        defectId="D1",
        execution="completed",
        resolution="analysis_only",
        parentAttemptId="a1",
    )
    save_analysis_snapshot(root, a2, build_snapshot_from_entry(_entry("D1", "second")))
    with pytest.raises(FeedbackFormError, match="stale"):
        parse_feedback_form(text, store=root)


def test_same_form_reimport_is_idempotent(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    filled = text.replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:q1 -->\nkeep a+b\n<!-- /ANSWER:q1 -->",
    )
    first = import_feedback(root, parse_feedback_form(filled, store=root))
    second = import_feedback(root, parse_feedback_form(filled, store=root))
    assert first.revisionId == second.revisionId
    form = tmp_path / "filled.md"
    form.write_text(filled, encoding="utf-8")
    assert platform_main(["feedback", "--root", str(root), "--file", str(form)]) == 0


def test_duplicate_answer_markers_rejected(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    dup = text + "\n<!-- ANSWER:q1 -->\nagain\n<!-- /ANSWER:q1 -->\n"
    with pytest.raises(FeedbackFormError, match="duplicate"):
        parse_feedback_form(dup, store=root)


def test_import_later_form_merges_onto_latest_revision(tmp_path: Path):
    root, text = _saved_form(tmp_path)
    answers = text.replace(
        "<!-- ANSWER:q1 -->\n\n<!-- /ANSWER:q1 -->",
        "<!-- ANSWER:q1 -->\nnew answer\n<!-- /ANSWER:q1 -->",
    )
    expected = text.replace(
        "<!-- ANSWER:expected -->\n\n<!-- /ANSWER:expected -->",
        "<!-- ANSWER:expected -->\nreturn a-b\n<!-- /ANSWER:expected -->",
    )
    import_feedback(root, parse_feedback_form(answers, store=root))
    rev = import_feedback(root, parse_feedback_form(expected, store=root))
    assert rev.expected == "return a-b"
    assert rev.questionAnswers[0].text == "new answer"
