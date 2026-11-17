"""产物内可填写 Markdown 反馈表。用户只填答复区，不必手写 JSON。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.analysis_report import AnalysisSnapshot
from bugfix_contracts.repair import Feedback, QuestionAnswer

FORM_MARKER = "BUGFIX_FEEDBACK_FORM"
_KNOWN_FIELDS = {
    "expected",
    "reject_hypothesis",
    "observed",
    "steps",
    "attachments",
    "application",
    "acceptance",
    "notes",
    "clear",
}
_ANSWER_RE = re.compile(
    r"<!--\s*ANSWER:(?P<qid>[^>]+)\s*-->(?P<body>.*?)<!--\s*/ANSWER:(?P=qid)\s*-->",
    re.S,
)
_META_RE = re.compile(r"^(formId|defectId|attemptId|digest|baseRevisionId):\s*(.*)$", re.M)


class FeedbackFormError(ValueError):
    """表单绑定或填写不合法。"""


def render_feedback_form(snapshot: AnalysisSnapshot) -> str:
    report = snapshot.ticketReport
    questions = list((report.rootCause.questions or []) if report.rootCause else [])
    lines = [
        f"<!-- {FORM_MARKER} -->",
        f"formId: {snapshot.digest[:12]}",
        f"defectId: {report.defectId}",
        f"attemptId: {report.attemptId or ''}",
        f"digest: {snapshot.digest}",
        f"baseRevisionId: {snapshot.baseRevisionId or ''}",
        "",
        "# 请只在 ANSWER 标记之间填写",
        "",
        f"outcome: {report.outcome}",
        f"summary: {(report.rootCause.summary if report.rootCause else '')}",
        "",
        "## 展示区（改这里不会导入）",
        f"expected: {(report.ticket.expected if report.ticket else '')}",
        "",
        "## 答复区",
        "",
        "### expected（可选，覆盖本轮验收目标）",
        "<!-- ANSWER:expected -->",
        "",
        "<!-- /ANSWER:expected -->",
        "",
        "### observed（可选）",
        "<!-- ANSWER:observed -->",
        "",
        "<!-- /ANSWER:observed -->",
        "",
        "### steps（可选）",
        "<!-- ANSWER:steps -->",
        "",
        "<!-- /ANSWER:steps -->",
        "",
        "### reject_hypothesis（可选）",
        "<!-- ANSWER:reject_hypothesis -->",
        "",
        "<!-- /ANSWER:reject_hypothesis -->",
        "",
        "### attachments（可选，每行一个）",
        "<!-- ANSWER:attachments -->",
        "",
        "<!-- /ANSWER:attachments -->",
        "",
        "### application（可选：unknown / not_applied / applied / partially_applied / modified / discarded）",
        "<!-- ANSWER:application -->",
        "",
        "<!-- /ANSWER:application -->",
        "",
        "### acceptance（可选：pending / accepted / partially_resolved / rejected / regression_reported）",
        "<!-- ANSWER:acceptance -->",
        "",
        "<!-- /ANSWER:acceptance -->",
        "",
        "### notes（可选补充）",
        "<!-- ANSWER:notes -->",
        "",
        "<!-- /ANSWER:notes -->",
        "",
        "### clear（可选，逗号分隔 observed,expected,steps）",
        "<!-- ANSWER:clear -->",
        "",
        "<!-- /ANSWER:clear -->",
        "",
    ]
    for question in questions:
        qid = question.id
        lines.extend(
            [
                f"### Q {qid} [{question.kind}/{question.category}]",
                f"{question.reason}",
                f"<!-- ANSWER:{qid} -->",
                "",
                f"<!-- /ANSWER:{qid} -->",
                "",
            ]
        )
    return "\n".join(lines).replace("\r\n", "\n")


def _meta(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _META_RE.finditer(text)}


def _answers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: set[str] = set()
    for match in _ANSWER_RE.finditer(text.replace("\r\n", "\n")):
        qid = match.group("qid").strip()
        if qid in seen:
            raise FeedbackFormError(f"duplicate ANSWER {qid}")
        seen.add(qid)
        out[qid] = match.group("body").strip("\n")
    return out


def form_fill_digest(text: str) -> str:
    answers = _answers(text)
    blob = "\n".join(f"{k}={v}" for k, v in sorted(answers.items())).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def parse_feedback_form(text: str, *, store: Path | str | Any) -> Feedback:
    """从快照核对绑定；主报告改动忽略，只取答复区。不在锁外选择父 revision。"""
    normalized = text.replace("\r\n", "\n")
    if FORM_MARKER not in normalized:
        raise FeedbackFormError("not a bugfix feedback form")
    meta = _meta(normalized)
    defect_id = meta.get("defectId") or ""
    attempt_id = meta.get("attemptId") or ""
    digest = meta.get("digest") or ""
    if not defect_id or not attempt_id or not digest:
        raise FeedbackFormError("form is missing defectId/attemptId/digest")
    from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot
    from bugfix_platform.agents.analyst.sessions import load_latest_attempt

    root = Path(store) if not hasattr(store, "load") else Path(getattr(store, "root", store))
    try:
        snapshot = load_analysis_snapshot(root, defect_id, attempt_id)
    except OSError as err:
        raise FeedbackFormError(f"snapshot missing: {err}") from err
    if snapshot.digest != digest:
        raise FeedbackFormError(
            f"stale form; current digest={snapshot.digest} attempt={attempt_id}"
        )
    latest = load_latest_attempt(root, defect_id)
    if latest is not None and latest.attemptId != attempt_id:
        raise FeedbackFormError(
            f"stale form; current attempt={latest.attemptId} form={attempt_id}"
        )
    if snapshot.ticketReport.defectId != defect_id:
        raise FeedbackFormError("form defectId does not match snapshot")
    known = {q.id for q in (snapshot.ticketReport.rootCause.questions or [])}
    filled = _answers(normalized)
    question_answers: list[QuestionAnswer] = []
    expected: Optional[str] = None
    reject: Optional[str] = None
    observed: Optional[str] = None
    steps: Optional[str] = None
    notes = ""
    attachments: list[str] = []
    application = "unknown"
    acceptance = "pending"
    clear_fields: list[str] = []
    for qid, body in filled.items():
        if not body.strip():
            continue
        if qid == "expected":
            expected = body.strip()
            continue
        if qid == "reject_hypothesis":
            reject = body.strip()
            continue
        if qid == "observed":
            observed = body.strip()
            continue
        if qid == "steps":
            steps = body.strip()
            continue
        if qid == "notes":
            notes = body.strip()
            continue
        if qid == "attachments":
            attachments = [line.strip() for line in body.splitlines() if line.strip()]
            continue
        if qid == "application":
            allowed_app = {"unknown", "not_applied", "applied", "partially_applied", "modified", "discarded"}
            application = body.strip() if body.strip() in allowed_app else "unknown"
            continue
        if qid == "acceptance":
            allowed_acc = {"pending", "accepted", "partially_resolved", "rejected", "regression_reported"}
            acceptance = body.strip() if body.strip() in allowed_acc else "pending"
            continue
        if qid == "clear":
            allowed_clear = {"observed", "expected", "steps"}
            clear_fields = [part.strip() for part in body.split(",") if part.strip() in allowed_clear]
            continue
        if qid not in known:
            raise FeedbackFormError(f"unknown question {qid}")
        question_answers.append(
            QuestionAnswer(questionId=qid, text=body.strip(), source="user")
        )
    kind = "unknown"
    if expected:
        kind = "change_expected"
    elif reject:
        kind = "reject_hypothesis"
    elif question_answers or observed or steps or notes or attachments:
        kind = "supplement_fact"
    fill = form_fill_digest(normalized)
    feedback_id = f"form-{meta.get('formId') or digest[:12]}-{fill[:10]}"
    for item in question_answers:
        item.answerRevisionId = item.answerRevisionId or feedback_id
    return Feedback(
        feedbackId=feedback_id,
        defectId=defect_id,
        attemptId=attempt_id,
        kind=kind,  # type: ignore[arg-type]
        parentRevisionId=snapshot.baseRevisionId,
        expected=expected,
        observed=observed,
        steps=steps,
        text=reject or notes,
        attachments=attachments,
        application=application,  # type: ignore[arg-type]
        acceptance=acceptance,  # type: ignore[arg-type]
        clearFields=clear_fields,  # type: ignore[arg-type]
        questionAnswers=question_answers,
        formId=meta.get("formId") or digest[:12],
    )


def archive_feedback_form(root: Path | str, feedback: Feedback, text: str) -> Path:
    dest = Path(root) / "defects" / feedback.defectId / "feedback" / "forms-archive" / f"{feedback.feedbackId}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
    tmp.replace(dest)
    return dest


def import_filled_form(root: Path | str, text: str, *, already_locked: bool = False) -> Any:
    from bugfix_platform.agents.analyst.attempt_store import store_lock
    from bugfix_platform.agents.analyst.feedback import import_feedback

    def _run() -> Any:
        feedback = parse_feedback_form(text, store=root)
        archive_feedback_form(root, feedback, text)
        return import_feedback(Path(root), feedback, already_locked=True)

    if already_locked:
        return _run()
    with store_lock(Path(root)):
        return _run()
