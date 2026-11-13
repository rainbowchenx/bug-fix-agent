"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

from bugfix_contracts import DefectBatch
from bugfix_agent1.defect_batch import run_defect_batch_prepare

ROOT = Path(__file__).resolve().parents[1]
HC1 = ROOT / "test" / "fixtures" / "defect-batch" / "hc1-raw.json"


def ensure_git_repo(path: Path, *, head: str = "a" * 40) -> Path:
    """Plant a minimal ``.git`` so ``discover_repo_roots`` accepts the path."""
    path.mkdir(parents=True, exist_ok=True)
    git = path / ".git"
    if not git.exists():
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        ref = git / "refs" / "heads"
        ref.mkdir(parents=True, exist_ok=True)
        (ref / "main").write_text(head[:40] + "\n", encoding="utf-8")
    return path


def defect_batch_from_hc1(*, posture: str = "alpha") -> DefectBatch:
    return run_defect_batch_prepare(
        product_line="hc",
        source=HC1,
        posture=posture,  # type: ignore[arg-type]
    )


def minimal_defect_batch() -> DefectBatch:
    return DefectBatch.model_validate(
        {
            "schemaVersion": "0.1.0",
            "productLine": "hc",
            "posture": "alpha",
            "generatedAt": "2026-11-05T00:00:00Z",
            "funnel": {"total": 0},
            "clusters": [],
            "tickets": [],
        }
    )
