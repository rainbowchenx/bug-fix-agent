"""T12：HEAD 相同但部分应用要识别。"""

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
