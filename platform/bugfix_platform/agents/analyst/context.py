"""组装单票 TaskContext：原文优先，附件未读不得杜撰。"""

from __future__ import annotations

from typing import Optional

from bugfix_contracts.code_knowledge import CodeKnowledge
from bugfix_contracts.defect_batch import BatchTicket
from bugfix_contracts.repair import (
    Evidence,
    InputRevision,
    SkillUsage,
    TaskContext,
    WorkspaceSnapshot,
)
from bugfix_platform.sdk.skill_inject import InjectedSkill


def build_task_context(
    ticket: BatchTicket,
    knowledge: Optional[CodeKnowledge] = None,
    revision: Optional[InputRevision] = None,
    snapshot: Optional[WorkspaceSnapshot] = None,
    *,
    generate_patch: bool = False,
    read_attachments: Optional[list[str]] = None,
) -> TaskContext:
    """把票面原文、上游线索和快照收成分析上下文。"""
    attachments = list(ticket.attachmentRefs or [])
    rev = revision or InputRevision(
        revisionId=ticket.revisionId or f"{ticket.defectId}:v0",
        defectId=ticket.defectId,
        observed=ticket.sourceObserved or ticket.observed,
        expected=ticket.sourceExpected or ticket.expected,
        steps=ticket.sourceSteps or ticket.steps,
        attachments=attachments,
        source="ticket",
    )
    actually_read = set(read_attachments or [])
    unread = [p for p in rev.attachments if p not in actually_read]
    evidence: list[Evidence] = []
    if knowledge is not None:
        match = next(
            (m for m in knowledge.defectCodeMatches if m.defectId == ticket.defectId),
            None,
        )
        if match is not None:
            status = match.investigationStatus or "search_draft"
            for i, cand in enumerate(match.candidates[:3], start=1):
                validity = "pending_review"
                if status in ("complete", "partial") and cand.source in {
                    "codegraph",
                    "grep",
                    "claude_md",
                }:
                    validity = "pending_review"
                evidence.append(
                    Evidence(
                        evidenceId=f"a2-{ticket.defectId}-{i}",
                        category="tool_result",
                        source=str(cand.source or "heuristic"),
                        summary=cand.why or cand.path,
                        path=cand.path,
                        repoId=cand.repoPath,
                        validity=validity,
                    )
                )
    conventions: list[str] = []
    spec_dirs: list[str] = []
    if knowledge is not None:
        conventions = list(knowledge.conventions.fromRules or [])
        spec_dirs = [
            e.path
            for e in knowledge.specAtlas.entries
            if e.kind in ("doc_ref", "guide")
        ]
    return TaskContext(
        defectId=ticket.defectId,
        revision=rev,
        snapshot=snapshot,
        evidence=evidence,
        conventions=conventions,
        specDirs=spec_dirs,
        unreadAttachments=unread,
        generatePatch=generate_patch,
    )


def skill_usage_from_injected(
    skill: InjectedSkill, *, selected: bool = False
) -> SkillUsage:
    """发现不等于执行。selected 默认不把 applied 打开。"""
    return SkillUsage(
        source=str(skill.source),
        repoId=getattr(skill, "repoId", ".") or ".",
        name=skill.name,
        selected=selected,
        applied=False,
    )
