import json
import subprocess
from hashlib import sha256

import pytest

from bugfix_contracts.repair import REPAIR_SCHEMA_VERSION, AttemptRecord, PatchSet, WorkspaceSnapshot
from bugfix_platform.agents.analyst.analysis_store import build_snapshot_from_entry, save_analysis_snapshot
from bugfix_platform.cli import main


@pytest.fixture
def staged_candidate(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args]).decode("utf-8").strip()

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.test")
    source = repo / "app.txt"
    source.write_text("old\n", encoding="utf-8")
    git("add", "app.txt")
    git("commit", "-m", "baseline")
    head = git("rev-parse", "HEAD")
    source.write_text("new\n", encoding="utf-8")
    git("add", "app.txt")

    root = tmp_path / "out"
    root.mkdir()
    bundle = root / "bundle.diff"
    bundle.write_bytes(subprocess.check_output(["git", "-C", str(repo), "diff", "--cached", "--binary"]))
    message = "fix: restore retry button\n\nKeep the existing timeout handling."
    ticket = {
        "defectId": "D1", "attemptId": "a1", "outcome": "patch_ready", "proposedFix": {"summary": "Retry"},
        "patch": {"path": str(bundle), "commitMessage": message, "bundleDigest": sha256(bundle.read_bytes()).hexdigest()},
    }

    def save_report(entry):
        (root / "analysis-report.json").write_text(json.dumps({
            "schemaVersion": "0.4.0", "productLine": "test", "workDir": str(repo),
            "generatedAt": "2026-11-19", "tickets": [entry],
        }), encoding="utf-8")

    def save_attempt(entry):
        patch = entry.get("patch")
        patch_set = PatchSet(
            patchSetId="patch", delivery="candidate", baselineHead=head,
            bundlePath=str(bundle), bundleDigest=patch["bundleDigest"],
            patches=[{"path": "app.txt", "archivePath": str(bundle), "digest": sha256(source.read_bytes()).hexdigest()}],
        ) if patch else None
        attempt = AttemptRecord(schemaVersion=REPAIR_SCHEMA_VERSION, defectId="D1", attemptId=entry["attemptId"],
                                execution="completed", patchSet=patch_set)
        snapshot = build_snapshot_from_entry(entry, workspace=WorkspaceSnapshot(repoId=str(repo), head=head))
        save_analysis_snapshot(root, attempt, snapshot)

    save_report(ticket)
    save_attempt(ticket)
    args = ["commit", "--root", str(root), "--defect-id", "D1"]
    return repo, git, head, ticket, bundle, args, save_report, save_attempt


def test_commit_uses_model_message_and_rejects_unrelated_staged_changes(staged_candidate, capsys):
    repo, git, head, ticket, _, args, _, _ = staged_candidate
    (repo / "extra.txt").write_text("unrelated\n", encoding="utf-8")
    git("add", "extra.txt")
    assert main(args) == 1
    assert git("rev-parse", "HEAD") == head
    assert git("diff", "--cached", "--name-only").splitlines() == ["app.txt", "extra.txt"]
    git("reset", "--", "extra.txt")

    assert main(args) == 0
    assert git("log", "-1", "--format=%B") == ticket["patch"]["commitMessage"]
    assert git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == "app.txt"
    assert git("status", "--porcelain") == "?? extra.txt"
    assert json.loads(capsys.readouterr().out)["commitSha"] == git("rev-parse", "HEAD")


@pytest.mark.parametrize("change", ["latest_plan", "latest_candidate", "modified_bundle", "missing_message", "legacy"])
def test_commit_rejects_candidate_without_current_verifiable_artifacts(staged_candidate, capsys, change):
    repo, git, head, ticket, bundle, args, save_report, save_attempt = staged_candidate
    current = {**ticket, "attemptId": "a2", "patch": dict(ticket["patch"])}
    if change == "latest_plan":
        save_attempt({**current, "outcome": "plan_only", "patch": None})
        message = "No candidate patch in latest attempt a2"
    elif change == "latest_candidate":
        save_attempt(current)
        message = "Report is stale"
    elif change == "modified_bundle":
        (repo / "app.txt").write_text("different\n", encoding="utf-8")
        git("add", "app.txt")
        bundle.write_bytes(subprocess.check_output(["git", "-C", str(repo), "diff", "--cached", "--binary"]))
        message = "bundle digest does not match"
    else:
        field = "commitMessage" if change == "missing_message" else "bundleDigest"
        current["patch"][field] = None
        save_attempt(current)
        save_report(current)
        message = "No usable model-generated commit message" if change == "missing_message" else "no recorded bundle digest"

    assert main(args) == 1
    assert message in capsys.readouterr().err
    assert git("rev-parse", "HEAD") == head
    assert git("diff", "--cached", "--name-only") == "app.txt"
