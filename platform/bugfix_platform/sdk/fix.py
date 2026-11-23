"""Agent-3 gated fix session: Edit/Write inside a per-ticket worktree."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.sdk.credentials import has_credentials
from bugfix_platform.sdk.parse import parse_json_payload
from bugfix_platform.sdk.skill_inject import InjectedSkill, fix_skills_addon
from bugfix_platform.sdk.skills import skills_system_addon

FIX_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write"]
DISALLOWED_TOOLS = ["Bash", "NotebookEdit"]
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class FixRequest:
    work_dir: str
    ticket: BatchTicket
    analysis: dict[str, Any]
    worktree_path: str
    artifact_dir: Optional[str] = None
    max_turns: int = 16
    model: Optional[str] = None
    injected_skills: tuple[InjectedSkill, ...] = ()


@dataclass
class FixResult:
    ok: bool
    payload: dict[str, Any]
    source: Literal["sdk", "sdk_fallback", "skipped"] = "skipped"
    detail: Optional[str] = None


FixRunner = Callable[[FixRequest], FixResult]


def apply_fix_from_env(explicit: Optional[bool] = None) -> bool:
    """Resolve ``--apply-fix`` / ``BUGFIX_APPLY_FIX`` (default off)."""
    if explicit is True or explicit is False:
        return explicit
    raw = (os.environ.get("BUGFIX_APPLY_FIX") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def ticket_worktree_slug(defect_id: str) -> str:
    slug = _SLUG_RE.sub("_", defect_id).strip("._") or "ticket"
    return slug[:80]


def ensure_ticket_worktree(work_dir: str | Path, defect_id: str) -> tuple[Path | None, str | None]:
    """Create ``workDir/.bugfix/worktrees/{id}`` from HEAD.

    Returns ``(path, None)`` on success, or ``(None, reason)`` when the workDir
    is not a git repo / worktree add failed.
    """
    root = Path(work_dir)
    check = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check.returncode != 0 or check.stdout.strip() != "true":
        return None, "workDir is not a git repository; skip apply-fix"
    dest = root / ".bugfix" / "worktrees" / ticket_worktree_slug(defect_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest, None
    added = subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(dest), "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if added.returncode != 0:
        return None, (added.stderr or added.stdout or "git worktree add failed").strip()[:300]
    return dest, None


def create_fix_runner() -> FixRunner:
    return run_claude_fix


def run_claude_fix(req: FixRequest) -> FixResult:
    """Edit inside the worktree; PatchSet collection judges the actual files."""
    if not has_credentials():
        return FixResult(
            ok=False,
            source="sdk_fallback",
            detail="no Anthropic credentials for apply-fix",
            payload={},
        )
    try:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
    except ImportError as err:
        return FixResult(
            ok=False,
            source="sdk_fallback",
            detail=f"claude-agent-sdk not installed ({err})",
            payload={},
        )

    prompt = _build_fix_prompt(req)
    model = req.model or os.environ.get("ANTHROPIC_MODEL") or None
    if req.injected_skills:
        system_prompt = _FIX_SYSTEM_PROMPT + fix_skills_addon(req.injected_skills)
    else:
        system_prompt = _FIX_SYSTEM_PROMPT + skills_system_addon(
            ("hierarchical-localization", "systematic-debugging")
        )
    options = ClaudeAgentOptions(
        cwd=req.worktree_path,
        system_prompt=system_prompt,
        allowed_tools=list(FIX_TOOLS),
        disallowed_tools=list(DISALLOWED_TOOLS),
        permission_mode="dontAsk",
        max_turns=req.max_turns,
        model=model,
    )

    texts: list[str] = []

    async def _run() -> None:
        terminal_error: str | None = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    if terminal_error is None:
                        terminal_error = "; ".join(message.errors or []) or message.result or "fix SDK error"
                    continue
                if isinstance(message.result, str) and message.result.strip():
                    texts.append(message.result)
        if terminal_error is not None:
            raise RuntimeError(terminal_error)

    try:
        anyio.run(_run)
    except Exception as err:  # noqa: BLE001
        return FixResult(
            ok=False,
            source="sdk_fallback",
            detail=f"sdk fix failed: {err}",
            payload={},
        )

    review = _parse_semantic_review(texts)
    payload: dict[str, Any] = {
        "outcome": "plan_only",
        "semanticReview": review["text"],
        "semanticReviewStatus": review["status"],
        "semanticReviewExecuted": review["status"] != "not_executed",
    }
    if review.get("commitMessage"):
        payload["commitMessage"] = review["commitMessage"]
    return FixResult(
        ok=True,
        source="sdk",
        payload=payload,
    )


_FIX_SYSTEM_PROMPT = """You are Agent-3 fix editor.
Apply the proposed fix already written in the analysis JSON.
Use Edit/Write only. Minimal diff. Do not expand scope.
Stay inside proposedFix.targetFiles unless a file you read proves another file is required.
Do not commit, push, or run tests. Do not invent extra features.
IRON LAW: if the analysis has no real root cause, make no edits.
After editing, Read the files you changed. End with a JSON object:
commitMessage: a concise Git subject describing the actual fix, with an optional body.
Include the defect ID. Omit it when no files changed.
semanticReviewStatus: passed | failed | not_executed
semanticReviewExecuted: true only if you judged the actual edited lines
semanticReview: how THIS diff restores expected behavior, whether success /
fail / retry paths remain, and which changed lines are the basis.
Judge the actual edits, not the analysis plan. Use failed if the change does
not restore the expected behavior or breaks a success/fail/retry path.
Do not emit a generic template. If you cannot judge, status=not_executed.
"""


_REVIEW_STATUSES = frozenset({"passed", "failed", "not_executed"})


def _annotate_review(review: str, reason: str) -> str:
    if review:
        return f"{reason}: {review}"
    return reason


def _parse_semantic_review(texts: list[str]) -> dict[str, str]:
    for text in reversed(texts):
        parsed = parse_json_payload(text)
        if not isinstance(parsed, dict):
            continue
        raw_message = parsed.get("commitMessage")
        message_fields = {}
        if isinstance(raw_message, str) and raw_message.strip():
            message_fields["commitMessage"] = raw_message.strip()
        review = str(parsed.get("semanticReview") or parsed.get("reviewConclusion") or "").strip()
        executed = parsed.get("semanticReviewExecuted")
        raw_status = parsed.get("semanticReviewStatus")
        if raw_status is None:
            raw_status = parsed.get("reviewStatus")
        status = str(raw_status or "").strip().lower()
        if executed is False:
            return {
                **message_fields,
                "status": "not_executed",
                "text": _annotate_review(review, "semanticReviewExecuted=false"),
            }
        if status in _REVIEW_STATUSES:
            if review:
                return {**message_fields, "status": status, "text": review}
            if status == "not_executed":
                return {**message_fields, "status": status, "text": "semantic review not executed"}
            return {**message_fields, "status": status, "text": f"semantic review {status}"}
        if not status:
            return {
                **message_fields,
                "status": "not_executed",
                "text": _annotate_review(review, "semantic review not executed (missing semanticReviewStatus)"),
            }
        return {
            **message_fields,
            "status": "not_executed",
            "text": _annotate_review(
                review, f"semantic review not executed (unknown semanticReviewStatus={status})"
            ),
        }
    return {"status": "not_executed", "text": "semantic review not executed"}


def _build_fix_prompt(req: FixRequest) -> str:
    t = req.ticket
    expected = t.expected or ""
    return (
        "Apply the proposed fix for this ticket in the current worktree.\n\n"
        f"defectId: {t.defectId}\n"
        f"title: {t.title}\n"
        f"expected: {expected}\n"
        f"analysis: {req.analysis}\n"
        f"previousAttempt: {json.dumps((req.analysis or {}).get('previousAttempt') or {}, ensure_ascii=False)}\n"
        "After the edits, Read the changed files and return JSON with "
        "commitMessage, semanticReviewStatus and semanticReview based on those exact lines.\n"
    )
