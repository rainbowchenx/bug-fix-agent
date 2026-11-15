"""T12：HEAD 相同但部分应用要识别；无关 dirty 不得判 applied。"""

from pathlib import Path

from bugfix_contracts.repair import PatchFile, PatchSet, WorkspaceSnapshot
from bugfix_platform.agents.analyst.feedback import classify_patch_state


def test_partial_apply_same_head():
    snap = WorkspaceSnapshot(repoId="/tmp/r", head="a" * 40, dirty=["src/a.ts"])
    patch = PatchSet(
        patchSetId="p1",
        delivery="candidate",
        baselineHead="a" * 40,
        patches=[
            PatchFile(
                path="src/a.ts",
                kind="modify",
                digest="aaa",
                archivePath="patches/a.diff",
            ),
            PatchFile(
                path="src/b.ts",
                kind="add",
                digest="bbb",
                archivePath="patches/b.diff",
            ),
        ],
    )
    state = classify_patch_state(patch, snap)
    assert state["application"] in ("partially_applied", "unknown")
    assert state["reason"]


def test_unrelated_dirty_is_unknown_not_applied(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "a.ts").write_text("unrelated local edit\n", encoding="utf-8")
    after = tmp_path / "a.after"
    after.write_text("the patched content\n", encoding="utf-8")
    snap = WorkspaceSnapshot(repoId=str(repo), head="a" * 40, dirty=["src/a.ts"])
    patch = PatchSet(
        patchSetId="p1",
        delivery="candidate",
        baselineHead="a" * 40,
        patches=[
            PatchFile(
                path="src/a.ts",
                kind="modify",
                digest="deadbeef",
                archivePath=str(after),
            )
        ],
    )
    state = classify_patch_state(patch, snap, worktree=repo)
    assert state["application"] == "unknown"
