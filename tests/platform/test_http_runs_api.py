import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from bugfix_platform.http import create_app
from bugfix_platform.workflow import ThreeAgentWorkflowResult, WorkflowArtifacts
from tests.helpers import defect_batch_from_hc1, minimal_defect_batch


def test_health():
    app = create_app(background=False)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body


def test_create_and_get_run_sync(tmp_path: Path):
    work = tmp_path / "repos"
    work.mkdir()
    (work / "package.json").write_text(
        json.dumps({"name": "mini", "dependencies": {"electron": "1"}}), encoding="utf-8"
    )
    (work / "src").mkdir()
    (work / "src" / "回放.ts").write_text("export {}\n", encoding="utf-8")

    batch_path = tmp_path / "defect-batch.json"
    batch_path.write_text(defect_batch_from_hc1().model_dump_json(), encoding="utf-8")

    app = create_app(background=False)
    client = TestClient(app)
    created = client.post(
        "/v1/runs",
        json={
            "workDir": str(work),
            "productLine": "hc",
            "defectBatch": str(batch_path),
            "posture": "alpha",
            "options": {
                "analyzeMode": "heuristic",
                "cartographyMode": "heuristic",
            },
        },
    )
    assert created.status_code == 202
    payload = created.json()
    run_id = payload["runId"]
    work_dir = payload["workDir"]

    got = client.get(f"/v1/runs/{run_id}", params={"workDir": work_dir})
    assert got.status_code == 200
    status = got.json()
    assert status["status"] == "succeeded"
    assert status["stage"] == "done"
    assert status["funnel"]["total"] == 50
    assert status["artifacts"]["defectBatchPath"]
    assert Path(status["artifacts"]["defectBatchPath"]).is_file()
    assert status["schemaVersion"] == "3-agent-0.1"


def test_create_run_forwards_cartography_profile(tmp_path: Path):
    work = tmp_path / "w"
    work.mkdir()
    captured: dict = {}

    def fake_workflow(**kwargs):
        captured.update(kwargs)
        return ThreeAgentWorkflowResult(ok=True, stage="done", artifacts=WorkflowArtifacts())

    app = create_app(workflow_fn=fake_workflow, background=False)
    client = TestClient(app)
    created = client.post(
        "/v1/runs",
        json={
            "workDir": str(work),
            "productLine": "hc",
            "defectBatch": minimal_defect_batch().model_dump(),
            "posture": "alpha",
            "options": {
                "skipAgent2": True,
                "skipAgent3": True,
                "cartographyProfile": "device_web",
            },
        },
    )
    assert created.status_code == 202
    assert captured.get("cartography_profile") == "device_web"


def test_get_run_404(tmp_path: Path):
    app = create_app(background=False)
    client = TestClient(app)
    r = client.get("/v1/runs/missing", params={"workDir": str(tmp_path)})
    assert r.status_code == 404


def test_create_run_with_injected_workflow(tmp_path: Path):
    work = tmp_path / "w"
    work.mkdir()

    def fake_workflow(**_kwargs):
        return ThreeAgentWorkflowResult(ok=True, stage="done", artifacts=WorkflowArtifacts())

    app = create_app(workflow_fn=fake_workflow, background=False)
    client = TestClient(app)
    created = client.post(
        "/v1/runs",
        json={
            "workDir": str(work),
            "productLine": "hc",
            "defectBatch": minimal_defect_batch().model_dump(),
            "posture": "alpha",
            "options": {"skipAgent2": True, "skipAgent3": True},
        },
    )
    assert created.status_code == 202
    run_id = created.json()["runId"]
    got = client.get(f"/v1/runs/{run_id}", params={"workDir": created.json()["workDir"]})
    assert got.json()["status"] == "succeeded"
