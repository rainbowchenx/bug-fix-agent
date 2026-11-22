"""Commit a reviewed and staged Agent3 candidate to the local repository."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from bugfix_contracts.analysis_report import AnalysisReport
from bugfix_platform.agents.analyst.analysis_store import load_analysis_snapshot, snapshot_digest
from bugfix_platform.agents.analyst.attempt_store import AttemptStoreBusy, store_lock
from bugfix_platform.agents.analyst.sessions import load_latest_attempt


def commit_candidate(root: Path, defect_id: str) -> str:
    root = root.resolve()
    with store_lock(root):
        return _commit_locked(root, defect_id)


def _commit_locked(root: Path, defect_id: str) -> str:
    attempt = load_latest_attempt(root, defect_id)
    if attempt is None or attempt.defectId != defect_id:
        raise ValueError(f"No committed analysis for {defect_id}")
    snapshot = load_analysis_snapshot(root, defect_id, attempt.attemptId)
    ticket = snapshot.ticketReport
    if (ticket.defectId != defect_id or ticket.attemptId != attempt.attemptId
            or ticket.outcome != "patch_ready" or not ticket.patch or not ticket.patch.path):
        raise ValueError(f"No candidate patch in latest attempt {attempt.attemptId} for {defect_id}")
    bundle_digest = ticket.patch.bundleDigest
    if not bundle_digest or not snapshot.workspaceSnapshot or not attempt.patchSet:
        raise ValueError(f"Candidate has no recorded bundle digest or workspace for {defect_id}; regenerate the candidate")
    if (attempt.patchSet.delivery != "candidate" or attempt.patchSet.bundleDigest != bundle_digest
            or attempt.patchSet.bundlePath != ticket.patch.path or attempt.analysisDigest != snapshot.digest
            or snapshot_digest(snapshot.model_dump()) != snapshot.digest):
        raise ValueError(f"Analysis snapshot does not match committed attempt {attempt.attemptId}")

    report = AnalysisReport.model_validate_json(
        (root / "analysis-report.json").read_text(encoding="utf-8")
    )
    reviewed = next((item for item in report.tickets if item.defectId == defect_id), None)
    if reviewed != ticket:
        raise ValueError(f"Report is stale for {defect_id}; latest attempt is {attempt.attemptId}")
    message = (ticket.patch.commitMessage or "").strip()
    if not message or "\0" in message:
        raise ValueError(f"No usable model-generated commit message for {defect_id}; regenerate the candidate")

    bundle = Path(ticket.patch.path)
    if not bundle.is_absolute():
        local = root / bundle
        bundle = local if local.is_file() else bundle.resolve()
    bundle = bundle.resolve()
    if not bundle.is_relative_to(root) or not bundle.is_file():
        raise ValueError("Candidate patch file is missing from the artifact root")
    content = bundle.read_bytes()
    if hashlib.sha256(content).hexdigest() != bundle_digest:
        raise ValueError("Candidate bundle digest does not match the committed analysis")

    repo = Path(snapshot.workspaceSnapshot.repoId).resolve()
    if Path(report.workDir).resolve() != repo:
        raise ValueError("Report workDir does not match the candidate workspace")

    def git(*args: str, env: dict[str, str] | None = None, stdin: bytes | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], input=stdin, capture_output=True, env=env, check=False,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(f"git {args[0]} failed: {detail}")
        return result.stdout.decode("utf-8", errors="replace").strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("The report workDir must be the Git repository root")
    for state in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        if (repo / git("rev-parse", "--git-path", state)).exists():
            raise ValueError("Finish the current Git operation before committing a candidate")

    head = git("rev-parse", "HEAD")
    with TemporaryDirectory(prefix="bugfix-commit-") as directory:
        candidate_env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", head, env=candidate_env)
        git("apply", "--cached", "-", env=candidate_env, stdin=content)
        expected = git("write-tree", env=candidate_env)
        if expected == git("rev-parse", f"{head}^{{tree}}"):
            raise ValueError("Candidate patch has no changes")
        if git("write-tree") != expected or git("rev-parse", "HEAD") != head:
            raise ValueError("Stage exactly this candidate's changes before committing")
        git("commit", "--cleanup=verbatim", "-F", "-", env=candidate_env, stdin=(message + "\n").encode("utf-8"))
        return git("rev-parse", "HEAD")
