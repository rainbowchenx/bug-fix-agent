from __future__ import annotations

from typing import Any, Optional

from bugfix_agent import __version__
from bugfix_agent.http.models import (
    CreateRunRequest,
    CreateRunResponse,
    HealthResponse,
    RunStatusResponse,
)
from bugfix_agent.http.runner import WorkflowFn, enqueue_run
from bugfix_agent.http.store import UnsafeRunPathError, meta_to_status, read_meta


def create_app(*, workflow_fn: Optional[WorkflowFn] = None, background: bool = True):
    """Build FastAPI app. `workflow_fn` / `background=False` are for tests."""
    try:
        from fastapi import FastAPI, HTTPException, Query
    except ImportError as err:  # pragma: no cover
        raise ImportError(
            'HTTP extra required: pip install -e ".[http]" (fastapi + uvicorn)'
        ) from err

    app = FastAPI(
        title="bugfix-agent",
        version=__version__,
        description="Three-agent defect workflow HTTP API (S4)",
    )
    app.state.workflow_fn = workflow_fn
    app.state.background = background

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ok=True, version=__version__)

    @app.post("/v1/runs", response_model=CreateRunResponse, status_code=202)
    def create_run(body: CreateRunRequest) -> CreateRunResponse:
        run_id, work_dir = enqueue_run(
            body,
            workflow_fn=app.state.workflow_fn,
            background=app.state.background,
        )
        return CreateRunResponse(runId=run_id, workDir=work_dir)

    @app.get("/v1/runs/{run_id}", response_model=RunStatusResponse)
    def get_run(
        run_id: str,
        workDir: str = Query(..., min_length=1, description="Same workDir used at create"),
    ) -> RunStatusResponse:
        try:
            meta = read_meta(workDir, run_id)
        except UnsafeRunPathError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        except FileNotFoundError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        return meta_to_status(meta)

    return app


def run_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    workflow_fn: Optional[WorkflowFn] = None,
) -> None:
    try:
        import uvicorn
    except ImportError as err:  # pragma: no cover
        raise ImportError(
            'HTTP extra required: pip install -e ".[http]" (fastapi + uvicorn)'
        ) from err

    loopback = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}
    if host not in loopback:
        import warnings

        warnings.warn(
            f"bugfix-agent serve binding to non-loopback host {host!r}: "
            "no auth; arbitrary workDir paths are writable. Prefer 127.0.0.1.",
            stacklevel=2,
        )

    app = create_app(workflow_fn=workflow_fn, background=True)
    uvicorn.run(app, host=host, port=port, log_level="info")
