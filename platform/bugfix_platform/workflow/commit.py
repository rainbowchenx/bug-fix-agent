"""Commit a reviewed and staged Agent3 candidate to the local repository."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from bugfix_contracts.analysis_report import AnalysisReport


def commit_candidate(root: Path, defect_id: str) -> str:
    root = root.resolve()
    report = AnalysisReport.model_validate_json(
        (root / "analysis-report.json").read_text(encoding="utf-8")
    )
    ticket = next((ticket for ticket in report.tickets if ticket.defectId == defect_id), None)
    if ticket is None or ticket.outcome != "patch_ready" or not ticket.patch or not ticket.patch.path:
        raise ValueError(f"No candidate patch for {defect_id}")
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

    repo = Path(report.workDir).resolve()

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
        git("apply", "--cached", str(bundle), env=candidate_env)
        expected = git("write-tree", env=candidate_env)
        if expected == git("rev-parse", f"{head}^{{tree}}"):
            raise ValueError("Candidate patch has no changes")
        if git("write-tree") != expected or git("rev-parse", "HEAD") != head:
            raise ValueError("Stage exactly this candidate's changes before committing")
        git("commit", "--cleanup=verbatim", "-F", "-", env=candidate_env, stdin=(message + "\n").encode("utf-8"))
        return git("rev-parse", "HEAD")
