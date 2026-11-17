"""会话续接：不用 cwd 最近会话猜测票身份。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from bugfix_contracts.repair import AttemptRecord, InputRevision, TaskContext
from bugfix_platform.agents.analyst.attempt_store import load_attempt

SessionAction = Literal["resume", "fork", "new"]


@dataclass
class SessionDecision:
    action: SessionAction
    sessionId: Optional[str] = None
    reason: str = ""


def choose_session(
    context: TaskContext,
    previous: AttemptRecord | None,
    cwd_recent_session_id: Optional[str] = None,
) -> SessionDecision:
    """缺历史或不可恢复则新开。cwd 最近会话一律忽略。"""
    del cwd_recent_session_id  # 明确不使用
    if previous is None or not previous.sessionId:
        return SessionDecision(action="new", reason="no recoverable session")
    if previous.resolution == "needs_information" and previous.sessionId:
        return SessionDecision(
            action="resume",
            sessionId=previous.sessionId,
            reason="continue after information",
        )
    return SessionDecision(action="new", reason="start fresh attempt")


def load_latest_attempt(root: Path, defect_id: str) -> Optional[AttemptRecord]:
    """读 ``latest.json`` 指向的完整 attempt；缺文件则 None。"""
    latest = Path(root) / "defects" / defect_id / "latest.json"
    if not latest.is_file():
        return None
    try:
        meta = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    path = meta.get("path")
    if not path:
        return None
    try:
        return load_attempt(Path(path))
    except (OSError, ValueError):
        return None


def load_revision(
    root: Path, defect_id: str, revision_id: Optional[str] = None
) -> Optional[InputRevision]:
    """从已导入反馈里取 revision；未指定则取该票最新一份。"""
    folder = Path(root) / "defects" / defect_id / "feedback"
    if not folder.is_dir():
        if revision_id:
            raise ValueError(f"unknown revision: {revision_id}")
        return None
    pointer = folder.parent / "feedback-latest.json"
    if revision_id is None and pointer.is_file():
        revision_id = str(json.loads(pointer.read_text(encoding="utf-8"))["revisionId"])
    files = sorted(folder.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    chosen: Optional[Path] = None
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rev_raw = payload.get("revision") or {}
        rid = str(rev_raw.get("revisionId") or "")
        if revision_id and rid == revision_id:
            chosen = path
            break
        if revision_id is None:
            chosen = path
    if chosen is None:
        if revision_id:
            raise ValueError(f"unknown revision: {revision_id}")
        return None
    payload = json.loads(chosen.read_text(encoding="utf-8"))
    return InputRevision.model_validate(payload["revision"])


def write_session_decision(root: Path, defect_id: str, decision: SessionDecision) -> Path:
    dest = Path(root) / "defects" / defect_id / "session-decision.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            {
                "action": decision.action,
                "sessionId": decision.sessionId,
                "reason": decision.reason,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return dest


def resume_from_store(
    root: Path, defect_id: str, revision_id: Optional[str] = None
) -> SessionDecision:
    """根据已落盘 attempt / revision 决定 resume 或 new，并写出决策。"""
    previous = load_latest_attempt(root, defect_id)
    revision = load_revision(root, defect_id, revision_id)
    ctx = TaskContext(defectId=defect_id, revision=revision)
    decision = choose_session(ctx, previous)
    write_session_decision(root, defect_id, decision)
    return decision
