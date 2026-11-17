"""改码门槛：结构/来源校验。空列表才允许编辑。"""

from __future__ import annotations

import re

from bugfix_contracts.repair import EditDecision, TaskContext

_PLACEHOLDER = re.compile(
    r"\b(pending|placeholder|tbd|todo|分析中|待补充)\b", re.I
)


def validate_edit_decision(context: TaskContext, decision: EditDecision) -> list[str]:
    """返回拒绝原因。空列表表示程序侧允许进入编辑。"""
    errors: list[str] = []
    if not (decision.behaviorTarget or "").strip():
        errors.append("missing behaviorTarget")
    if not (decision.codeAssociation or "").strip():
        errors.append("missing codeAssociation")
    if not (decision.mechanism or "").strip():
        errors.append("missing mechanism")
    if _PLACEHOLDER.search(decision.mechanism or "") or _PLACEHOLDER.search(
        decision.editRationale or ""
    ):
        errors.append("placeholder analysis")
    if decision.questions is None:
        if decision.openQuestions:
            errors.append("open questions unresolved")
    elif any(q.kind in {"blocking", "choice"} for q in decision.questions):
        errors.append("blocking question unresolved")
    if not decision.evidenceRefs:
        errors.append("missing evidenceRefs")
    by_id = {e.evidenceId: e for e in context.evidence}
    for ref in decision.evidenceRefs:
        ev = by_id.get(ref)
        if ev is None:
            errors.append(f"unknown evidence {ref}")
            continue
        if ev.validity in ("invalid", "historical"):
            errors.append(f"invalid evidence {ref}")
        if ev.validity == "pending_review":
            errors.append(f"unverified evidence {ref}")
    if context.unreadAttachments and "screenshot" in (decision.mechanism or "").lower():
        errors.append("unread attachment cannot support visual claim")
    return errors
