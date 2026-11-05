"""Async run executor for ``POST /v1/runs``.

Lifecycle
---------
1. Allocate ``{workDir}/.bugfix-runs/{runId}/`` and write ``meta.json`` (queued).
2. Start a daemon thread (or run sync in tests with ``background=False``).
3. While LangGraph streams state values, polish ``meta.stage`` for polling clients.
4. On finish, rewrite artifacts + final meta (succeeded/failed).

Layout::

    {workDir}/.bugfix-runs/{runId}/
        meta.json
        artifacts/
            defect-batch.json
            code-knowledge.json
            analysis-report.json
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional, Union

from bugfix_agent.http.models import CreateRunOptions, CreateRunRequest
from bugfix_agent.http.store import artifact_paths, create_run_dir, update_meta, write_meta
from bugfix_agent.workflow import run_three_agent_workflow

log = logging.getLogger(__name__)

WorkflowFn = Callable[..., Any]


def enqueue_run(
    request: CreateRunRequest,
    *,
    workflow_fn: Optional[WorkflowFn] = None,
    background: bool = True,
) -> tuple[str, str]:
    """Persist run meta and start the three-agent workflow (thread or sync).

    Returns `(runId, resolvedWorkDir)`.
    """
    work_dir = str(Path(request.workDir).resolve())
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    run_id, root = create_run_dir(work_dir)
    opts = request.options or CreateRunOptions()
    write_meta(
        work_dir,
        run_id,
        {
            "runId": run_id,
            "workDir": work_dir,
            "productLine": request.productLine,
            "posture": request.posture,
            "status": "queued",
            "stage": "agent1",
            "error": None,
            "schemaVersion": "3-agent-0.1",
            "request": {
                "sourceType": type(request.source).__name__,
                "options": opts.model_dump(),
            },
            "artifacts": {},
        },
    )

    def _execute() -> None:
        update_meta(work_dir, run_id, status="running")
        fn = workflow_fn or run_three_agent_workflow
        art_dir = root / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)
        last_stage = "agent1"

        def _on_update(state: dict[str, Any]) -> None:
            """Mirror LangGraph ``stage`` into meta.json for GET pollers."""
            nonlocal last_stage
            stage = state.get("stage") or last_stage
            if stage != last_stage:
                last_stage = stage
                update_meta(
                    work_dir,
                    run_id,
                    status="running",
                    stage=stage,
                    error=state.get("error"),
                )

        try:
            call_kwargs: dict[str, Any] = {
                "work_dir": work_dir,
                "product_line": request.productLine,
                "source": request.source,
                "posture": request.posture,
                "open_mr": opts.openMr,
                "skip_agent2": opts.skipAgent2,
                "skip_agent3": opts.skipAgent3,
                "analyze_mode": opts.analyzeMode,
                "cartography_mode": opts.cartographyMode,
            }
            # Progressive artifact writes + stage streaming when using the
            # built-in LangGraph runner. Injected workflow_fn (tests) may not
            # accept these kwargs.
            if workflow_fn is None:
                call_kwargs.update(
                    {
                        "artifact_dir": str(art_dir),
                        "thread_id": run_id,
                        "on_update": _on_update,
                    }
                )
            try:
                result = fn(**call_kwargs)
            except TypeError:
                call_kwargs.pop("artifact_dir", None)
                call_kwargs.pop("thread_id", None)
                call_kwargs.pop("on_update", None)
                result = fn(**call_kwargs)
            # Ensure artifacts exist even if progressive persist was skipped
            # (injected workflow_fn or older call path).
            if result.artifacts.defect_batch:
                (art_dir / "defect-batch.json").write_text(
                    result.artifacts.defect_batch.model_dump_json(indent=2), encoding="utf-8"
                )
            if result.artifacts.code_knowledge:
                (art_dir / "code-knowledge.json").write_text(
                    result.artifacts.code_knowledge.model_dump_json(indent=2), encoding="utf-8"
                )
            if result.artifacts.analysis_report:
                (art_dir / "analysis-report.json").write_text(
                    result.artifacts.analysis_report.model_dump_json(indent=2), encoding="utf-8"
                )
            refs = artifact_paths(work_dir, run_id)
            update_meta(
                work_dir,
                run_id,
                status="succeeded" if result.ok else "failed",
                stage=result.stage,
                error=result.error,
                funnel=(
                    result.artifacts.defect_batch.funnel
                    if result.artifacts.defect_batch
                    else None
                ),
                profile=(
                    result.artifacts.code_knowledge.cartographyProfile
                    if result.artifacts.code_knowledge
                    else None
                ),
                summary=(
                    result.artifacts.analysis_report.summary.model_dump()
                    if result.artifacts.analysis_report and result.artifacts.analysis_report.summary
                    else None
                ),
                artifacts=refs.model_dump(),
            )
        except Exception as err:  # noqa: BLE001
            log.exception("run %s failed", run_id)
            update_meta(
                work_dir,
                run_id,
                status="failed",
                stage=last_stage,
                error=str(err),
            )

    if background:
        import threading

        # Fire-and-forget: POST returns 202; client polls GET /v1/runs/:id.
        threading.Thread(target=_execute, name=f"bugfix-run-{run_id}", daemon=True).start()
    else:
        _execute()
    return run_id, work_dir
