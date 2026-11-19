import json
import subprocess

from bugfix_platform.cli import main


def test_commit_uses_model_message_and_rejects_unrelated_staged_changes(tmp_path, capsys):
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
        "defectId": "D1", "outcome": "patch_ready", "proposedFix": {"summary": "Retry"},
        "patch": {"path": str(bundle), "commitMessage": message},
    }

    def save():
        (root / "analysis-report.json").write_text(json.dumps({
            "schemaVersion": "0.4.0", "productLine": "test", "workDir": str(repo),
            "generatedAt": "2026-11-19", "tickets": [ticket],
        }), encoding="utf-8")

    save()
    (repo / "extra.txt").write_text("unrelated\n", encoding="utf-8")
    git("add", "extra.txt")
    args = ["commit", "--root", str(root), "--defect-id", "D1"]
    assert main(args) == 1
    assert git("rev-parse", "HEAD") == head
    assert git("diff", "--cached", "--name-only").splitlines() == ["app.txt", "extra.txt"]
    git("reset", "--", "extra.txt")

    del ticket["patch"]["commitMessage"]
    save()
    assert main(args) == 1
    assert git("rev-parse", "HEAD") == head

    ticket["patch"]["commitMessage"] = message
    save()
    assert main(args) == 0
    assert git("log", "-1", "--format=%B") == message
    assert git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == "app.txt"
    assert git("status", "--porcelain") == "?? extra.txt"
    assert json.loads(capsys.readouterr().out)["commitSha"] == git("rev-parse", "HEAD")
