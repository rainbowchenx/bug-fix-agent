"""Agent-3 gated fix session: Edit/Write inside a per-ticket worktree."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from bugfix_contracts.defect_batch import BatchTicket
from bugfix_platform.sdk.credentials import has_credentials
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


def collect_worktree_diff(worktree: str | Path) -> str:
    """Return ``git diff`` inside the worktree (deterministic; not model Bash)."""
    proc = subprocess.run(
        ["git", "-C", str(worktree), "diff", "--binary"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout or ""


def write_patch_file(
    *,
    work_dir: str | Path,
    defect_id: str,
    diff: str,
    artifact_dir: Optional[str] = None,
) -> Path:
    """Write ``{artifactDir|workDir/.bugfix/patches}/{id}.patch``."""
    slug = ticket_worktree_slug(defect_id)
    base = Path(artifact_dir) if artifact_dir else Path(work_dir) / ".bugfix" / "patches"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{slug}.patch"
    path.write_text(diff, encoding="utf-8")
    return path


def create_fix_runner() -> FixRunner:
    return run_claude_fix


def run_claude_fix(req: FixRequest) -> FixResult:
    """Edit inside the worktree, then collect a git diff as the patch artifact."""
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

    async def _run() -> None:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage) and message.is_error:
                raise RuntimeError(
                    "; ".join(message.errors or []) or message.result or "fix SDK error"
                )

    try:
        anyio.run(_run)
    except Exception as err:  # noqa: BLE001
        return FixResult(
            ok=False,
            source="sdk_fallback",
            detail=f"sdk fix failed: {err}",
            payload={},
        )

    diff = collect_worktree_diff(req.worktree_path)
    if not diff.strip():
        return FixResult(
            ok=True,
            source="sdk",
            detail="fix session produced empty diff",
            payload={},
        )
    path = write_patch_file(
        work_dir=req.work_dir,
        defect_id=req.ticket.defectId,
        diff=diff,
        artifact_dir=req.artifact_dir,
    )
    summary = ((req.analysis.get("proposedFix") or {}) or {}).get("summary") or "apply proposed fix"
    return FixResult(
        ok=True,
        source="sdk",
        payload={
            "outcome": "patch_ready",
            "patch": {"path": str(path), "summary": str(summary)[:240]},
        },
    )


_FIX_SYSTEM_PROMPT = """You are Agent-3 fix editor.
Apply the proposed fix already written in the analysis JSON.
Use Edit/Write only. Minimal diff. Do not expand scope.
Stay inside proposedFix.targetFiles unless a file you read proves another file is required.
Do not commit, push, or run tests. Do not invent extra features.
IRON LAW: if the analysis has no real root cause, make no edits.
"""


def _build_fix_prompt(req: FixRequest) -> str:
    t = req.ticket
    return (
        "Apply the proposed fix for this ticket in the current worktree.\n\n"
        f"defectId: {t.defectId}\n"
        f"title: {t.title}\n"
        f"analysis: {req.analysis}\n"
    )
