"""逐票分析快照：先写 snapshot，再写 attempt，再写表单钩子，最后原子 latest。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

from bugfix_contracts.analysis_report import AnalysisSnapshot, TicketReport
from bugfix_contracts.repair import AnalysisSnapshotRef, AttemptRecord, Question
from bugfix_platform.agents.analyst.attempt_store import save_attempt, store_lock

_ANSWER_BODY = re.compile(
    r"<!--\s*ANSWER:(?P<qid>[^>]+)\s*-->(?P<body>.*?)<!--\s*/ANSWER:(?P=qid)\s*-->",
    re.S,
)


class SnapshotConflict(ValueError):
    """同一 attempt 已有不同 digest 的快照，拒绝覆盖。"""


def snapshot_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "digest"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def snapshot_path(root: Path | str, defect_id: str, attempt_id: str) -> Path:
    return Path(root) / "defects" / defect_id / "attempts" / attempt_id / "analysis.json"


def load_analysis_snapshot(root: Path | str, defect_id: str, attempt_id: str) -> AnalysisSnapshot:
    path = snapshot_path(root, defect_id, attempt_id)
    return AnalysisSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def _form_has_user_text(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    for match in _ANSWER_BODY.finditer(text.replace("\r\n", "\n")):
        if match.group("body").strip():
            return True
    return False


def _complete_commit(
    base: Path,
    attempt: AttemptRecord,
    dest: Path,
    digest: str,
    payload: dict[str, Any],
    form_text: str,
    *,
    update_latest: bool = True,
) -> AnalysisSnapshotRef:
    ref = AnalysisSnapshotRef(path=str(dest), digest=digest, attemptId=attempt.attemptId)
    bound = attempt.model_copy(update={"analysisRef": ref, "analysisDigest": digest})
    attempt_path = dest.parent / "attempt.json"
    recovering = not attempt_path.is_file()
    if recovering:
        saved = save_attempt(base, bound, already_locked=True, update_latest=False)
    else:
        saved = attempt_path
    form = dest.parent / "feedback-form.md"
    if not form.exists():
        text = form_text
        if not text:
            from bugfix_platform.agents.analyst.feedback_document import render_feedback_form
            text = render_feedback_form(AnalysisSnapshot.model_validate(payload))
        tmp_form = form.with_suffix(".md.tmp")
        tmp_form.write_text(text, encoding="utf-8")
        tmp_form.replace(form)
    from bugfix_platform.agents.analyst.attempt_store import _write_latest
    latest = base / "defects" / attempt.defectId / "latest.json"
    advance = bool(update_latest or recovering or not latest.is_file())
    if not advance and latest.is_file():
        try:
            meta = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        advance = meta.get("attemptId") in {None, attempt.attemptId}
    if advance:
        _write_latest(base, attempt.defectId, attempt.attemptId, saved)
    latest_form = base / "defects" / attempt.defectId / "feedback-form.md"
    if form.exists() and not _form_has_user_text(latest_form):
        latest_form.write_text(form.read_text(encoding="utf-8"), encoding="utf-8")
    return ref


def save_analysis_snapshot(
    root: Path | str,
    attempt: AttemptRecord,
    snapshot: AnalysisSnapshot,
    *,
    already_locked: bool = False,
    form_text: str = "",
) -> AnalysisSnapshotRef:
    """提交顺序：analysis → attempt → 初始表 → latest。写失败不覆盖旧 latest。同 digest 重试补齐。"""

    def _write(base: Path) -> AnalysisSnapshotRef:
        dest = snapshot_path(base, attempt.defectId, attempt.attemptId)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.model_dump()
        digest = snapshot.digest or snapshot_digest(payload)
        payload["digest"] = digest
        if dest.is_file():
            existing = json.loads(dest.read_text(encoding="utf-8"))
            if existing.get("digest") == digest:
                return _complete_commit(
                    base, attempt, dest, digest, existing, form_text, update_latest=False
                )
            raise SnapshotConflict(
                f"attempt {attempt.attemptId} already stored with a different digest"
            )
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(dest)
        return _complete_commit(
            base, attempt, dest, digest, payload, form_text, update_latest=True
        )

    if already_locked:
        return _write(Path(root))
    with store_lock(Path(root)) as base:
        return _write(base)


def _ledger_from_entry(
    report: TicketReport,
    resolutions: Optional[list] = None,
    previous_ledger: Optional[list] = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, Question] = {}
    for raw in previous_ledger or []:
        question = raw if isinstance(raw, Question) else Question.model_validate(raw)
        by_id[question.id] = question
    for question in list(report.rootCause.questions or []) if report.rootCause else []:
        by_id[question.id] = question
    resolved = set()
    for item in resolutions or []:
        qid = getattr(item, "questionId", None) or (item.get("questionId") if isinstance(item, dict) else None)
        disp = getattr(item, "disposition", None) or (item.get("disposition") if isinstance(item, dict) else None)
        if qid and disp == "resolved":
            resolved.add(str(qid))
    out = []
    for question in by_id.values():
        if question.id in resolved and question.status != "resolved":
            question = question.model_copy(update={"status": "resolved"})
        out.append(question.model_dump())
    return out


def build_snapshot_from_entry(
    entry: dict[str, Any],
    *,
    revision=None,
    workspace=None,
    parent_attempt_id: Optional[str] = None,
    resolutions: Optional[list] = None,
    previous_ledger: Optional[list] = None,
) -> AnalysisSnapshot:
    report = TicketReport.model_validate(entry)
    payload = {
        "ticketReport": report.model_dump(),
        "effectiveRevision": revision.model_dump() if revision is not None else None,
        "workspaceSnapshot": workspace.model_dump() if workspace is not None else None,
        "questionResolutions": [r.model_dump() if hasattr(r, "model_dump") else r for r in (resolutions or [])],
        "questionLedger": _ledger_from_entry(report, resolutions, previous_ledger),
        "parentAttemptId": parent_attempt_id,
        "baseRevisionId": getattr(revision, "revisionId", None) if revision is not None else None,
    }
    digest = snapshot_digest(payload)
    return AnalysisSnapshot.model_validate({**payload, "digest": digest})
