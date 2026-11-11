"""``POST /v1/runs`` 的异步执行器。

生命周期
--------
1. 分配 ``{workDir}/.bugfix-runs/{runId}/`` 并写 ``meta.json``（queued）。
2. 起守护线程（测试可 ``background=False`` 同步跑）。
3. LangGraph 流式输出 state 时，同步刷新 ``meta.stage`` 供轮询。
4. 结束后重写产物 + 最终 meta（succeeded/failed）。

目录布局::

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

from bugfix_platform.http.models import CreateRunOptions, CreateRunRequest
from bugfix_platform.http.store import artifact_paths, create_run_dir, update_meta, write_meta
from bugfix_platform.workflow import run_three_agent_workflow

log = logging.getLogger(__name__)

WorkflowFn = Callable[..., Any]


def enqueue_run(
    request: CreateRunRequest,
    *,
    workflow_fn: Optional[WorkflowFn] = None,
    background: bool = True,
) -> tuple[str, str]:
    """落盘 run meta，并启动三 Agent 工作流（线程或同步）。

    返回 ``(runId, resolvedWorkDir)``。
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
            "stage": "agent2",
            "error": None,
            "schemaVersion": "3-agent-0.1",
            "request": {
                "defectBatchType": type(request.defectBatch).__name__,
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
        last_stage = "agent2"

        def _on_update(state: dict[str, Any]) -> None:
            """把 LangGraph 的 ``stage`` 镜像进 meta.json，供 GET 轮询。"""
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
                "defect_batch": request.defectBatch,
                "posture": request.posture,
                "open_mr": opts.openMr,
                "apply_fix": True if opts.applyFix else None,
                "skip_agent2": opts.skipAgent2,
                "skip_agent3": opts.skipAgent3,
                "analyze_mode": opts.analyzeMode,
                "cartography_mode": opts.cartographyMode,
            }
            if opts.cartographyProfile:
                call_kwargs["cartography_profile"] = opts.cartographyProfile
            if opts.skillsDirs:
                call_kwargs["extra_skill_dirs"] = list(opts.skillsDirs)
            # 内置 LangGraph runner：渐进落盘 + 阶段流式。
            # 测试注入的 workflow_fn 可能不接受这些 kwargs。
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
                call_kwargs.pop("extra_skill_dirs", None)
                result = fn(**call_kwargs)
            # 即便跳过了渐进落盘（注入桩 / 旧路径），收尾也要保证产物在盘上。
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

        # 即发即忘：POST 返回 202；客户端轮询 GET /v1/runs/:id。
        threading.Thread(target=_execute, name=f"bugfix-run-{run_id}", daemon=True).start()
    else:
        _execute()
    return run_id, work_dir
