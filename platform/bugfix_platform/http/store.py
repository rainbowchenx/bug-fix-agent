from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bugfix_platform.http.models import RunArtifactsRef, RunStatusResponse

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafeRunPathError(ValueError):
    """Raised when runId / workDir would escape the runs root."""


def runs_root(work_dir: str | Path) -> Path:
    return Path(work_dir).resolve() / ".bugfix-runs"


def assert_safe_run_id(run_id: str) -> str:
    if not run_id or not RUN_ID_RE.fullmatch(run_id):
        raise UnsafeRunPathError(f"invalid runId: {run_id!r}")
    if ".." in run_id or "/" in run_id or "\\" in run_id:
        raise UnsafeRunPathError(f"invalid runId: {run_id!r}")
    return run_id


def run_dir(work_dir: str | Path, run_id: str) -> Path:
    """Resolved `{workDir}/.bugfix-runs/{runId}` that cannot escape the runs root."""
    assert_safe_run_id(run_id)
    root = runs_root(work_dir)
    path = (root / run_id).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as err:
        raise UnsafeRunPathError(f"run path escapes workDir: {run_id!r}") from err
    return path


def create_run_dir(work_dir: str | Path) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    assert_safe_run_id(run_id)
    root = run_dir(work_dir, run_id)
    root.mkdir(parents=True, exist_ok=False)
    (root / "artifacts").mkdir()
    return run_id, root


def meta_path(work_dir: str | Path, run_id: str) -> Path:
    return run_dir(work_dir, run_id) / "meta.json"


def write_meta(work_dir: str | Path, run_id: str, meta: dict[str, Any]) -> None:
    path = meta_path(work_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_meta(work_dir: str | Path, run_id: str) -> dict[str, Any]:
    path = meta_path(work_dir, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def update_meta(work_dir: str | Path, run_id: str, **patch: Any) -> dict[str, Any]:
    meta = read_meta(work_dir, run_id)
    meta.update(patch)
    meta["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_meta(work_dir, run_id, meta)
    return meta


def artifact_paths(work_dir: str | Path, run_id: str) -> RunArtifactsRef:
    art = run_dir(work_dir, run_id) / "artifacts"

    def _if(name: str) -> Optional[str]:
        p = art / name
        return str(p) if p.is_file() else None

    return RunArtifactsRef(
        defectBatchPath=_if("defect-batch.json"),
        codeKnowledgePath=_if("code-knowledge.json"),
        analysisReportPath=_if("analysis-report.json"),
    )


def meta_to_status(meta: dict[str, Any]) -> RunStatusResponse:
    arts = meta.get("artifacts") or {}
    return RunStatusResponse(
        runId=meta["runId"],
        workDir=meta["workDir"],
        status=meta.get("status") or "queued",
        stage=meta.get("stage"),
        error=meta.get("error"),
        funnel=meta.get("funnel"),
        profile=meta.get("profile"),
        summary=meta.get("summary"),
        artifacts=RunArtifactsRef(
            defectBatchPath=arts.get("defectBatchPath"),
            codeKnowledgePath=arts.get("codeKnowledgePath"),
            analysisReportPath=arts.get("analysisReportPath"),
        ),
        schemaVersion=meta.get("schemaVersion") or "3-agent-0.1",
    )
