"""Regression tests for review Top-8 hardening."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bugfix_agent.agents.analyst.run import run_analyst
from bugfix_agent.agents.cartographer.match import filter_existing_candidates, match_tickets
from bugfix_agent.contracts import (
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    BatchTicket,
    CodeKnowledge,
    DefectBatch,
    DefectCodeMatch,
    MatchCandidate,
    RawDefect,
)
from bugfix_agent.defect_batch.distill import distill_defect
from bugfix_agent.defect_batch.screen import funnel_counts, screen_digest
from bugfix_agent.http.store import UnsafeRunPathError, assert_safe_run_id, meta_path, run_dir
from bugfix_agent.workflow import run_three_agent_workflow


def test_flow_status_cancel_excludes():
    raw = RawDefect(
        defectId="fs1",
        title="已取消流程票",
        description="预期结果：应关闭\n实际结果：仍开着",
        status="Open",
        flowStatus="Cancel",
        testModule="m",
    )
    d = distill_defect(raw)
    assert d.flowStatus == "Cancel"
    s = screen_digest(d, posture="alpha")
    assert s.pool == "excluded"
    assert s.reasonCode == "R1"


def test_duplicate_pool_and_funnel_no_double_count():
    raw = RawDefect(
        defectId="dup1",
        title="重复票",
        description="预期结果：x\n实际结果：y",
        status="Open",
        duplicateOf="100",
        testModule="m",
    )
    d = distill_defect(raw)
    assert d.duplicate is True
    s = screen_digest(d, posture="alpha")
    assert s.pool == "duplicate"
    counts = funnel_counts([s])
    assert counts["duplicate"] == 1
    assert counts["excluded"] == 0
    assert counts["total"] == 1


def test_skip_agent2_alone_rejected(tmp_path: Path):
    result = run_three_agent_workflow(
        work_dir=tmp_path,
        product_line="hc",
        posture="alpha",
        source={"tickets": []},
        skip_agent2=True,
        skip_agent3=False,
    )
    assert result.ok is False
    assert result.stage == "agent2"
    assert "skip_agent2" in (result.error or "")


def test_http_run_id_rejects_traversal(tmp_path: Path):
    with pytest.raises(UnsafeRunPathError):
        assert_safe_run_id("../../outside")
    with pytest.raises(UnsafeRunPathError):
        meta_path(tmp_path, "../../outside")
    with pytest.raises(UnsafeRunPathError):
        run_dir(tmp_path, "evil/../x")
    safe = run_dir(tmp_path, "20261105T000000Z-abcd1234")
    assert safe.resolve().is_relative_to((tmp_path / ".bugfix-runs").resolve())


def test_filter_existing_candidates_drops_missing(tmp_path: Path):
    (tmp_path / "src").mkdir()
    real = tmp_path / "src" / "ok.ts"
    real.write_text("export {}\n", encoding="utf-8")
    matches = [
        DefectCodeMatch(
            defectId="1",
            candidates=[
                MatchCandidate(path="src/ok.ts", why="hit", source="heuristic"),
                MatchCandidate(path="src/missing.ts", why="hallucinated", source="heuristic"),
            ],
            confidence="medium",
        )
    ]
    filtered = filter_existing_candidates(tmp_path, matches)
    assert len(filtered[0].candidates) == 1
    assert filtered[0].candidates[0].path == "src/ok.ts"


def test_match_tickets_only_existing_paths(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    tickets = [
        BatchTicket(
            defectId="t1",
            title="preview player 回放异常",
            pool="strict",
            expectQuality="explicit",
            observed="回放失败",
            expected="正常预览",
        )
    ]
    from bugfix_agent.agents.cartographer.detect import discover_repo_roots

    roots = discover_repo_roots(tmp_path)
    matched = filter_existing_candidates(tmp_path, match_tickets(tmp_path, roots, tickets))
    for m in matched:
        for c in m.candidates:
            assert (tmp_path / c.path).is_file()


def test_analyst_invalid_ticket_becomes_other_blocked(tmp_path: Path):
    batch = DefectBatch(
        schemaVersion="0.1.0",
        productLine="hc",
        posture="alpha",
        generatedAt="2026-11-05T00:00:00Z",
        funnel={"total": 1, "strict": 1},
        clusters=[],
        tickets=[
            BatchTicket(
                defectId="bad1",
                title="t",
                pool="strict",
                expectQuality="explicit",
                observed="o",
                expected="e",
            )
        ],
    )
    knowledge = CodeKnowledge(
        schemaVersion=CODE_KNOWLEDGE_SCHEMA_VERSION,
        productLine="hc",
        workDir=str(tmp_path),
        generatedAt="2026-11-05T00:00:00Z",
        cartographyProfile="unknown",
        repoRoots=[],
        defectCodeMatches=[
            DefectCodeMatch(
                defectId="bad1",
                candidates=[MatchCandidate(path="x.ts", why="x", source="heuristic")],
                confidence="medium",
            )
        ],
    )

    def bad_analyze(req):
        from bugfix_agent.sdk.analyze import AnalyzeResult

        return AnalyzeResult(
            ok=True,
            source="heuristic",
            payload={
                "outcome": "plan_only",
                # missing proposedFix.summary → TicketReport validation fails
                "proposedFix": None,
                "localization": {"candidates": []},
                "rootCause": {"summary": "x"},
                "confidence": "low",
            },
            detail="injected invalid",
        )

    report = run_analyst(
        work_dir=tmp_path,
        defect_batch=batch,
        code_knowledge=knowledge,
        analyze_fn=bad_analyze,
    )
    assert report.tickets[0].outcome == "other_blocked"
    assert report.tickets[0].blockers is not None
    assert "invalid ticket" in (report.tickets[0].blockers.detail or "")


def test_cli_writes_out_dir_on_failure(tmp_path: Path, monkeypatch):
    from bugfix_agent import cli as cli_mod

    out = tmp_path / "out"
    work = tmp_path / "work"
    work.mkdir()
    # Minimal batch that Agent-1 can produce; force skip_agent2 alone via argv path
    # Use workflow that fails after Agent-1 by injecting bad agent2 through env is hard;
    # instead call cli main with source that works then skip flags that fail early.
    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            {
                "tickets": [
                    {
                        "defectId": "1",
                        "title": "t",
                        "description": "预期结果：ok\n实际结果：bad",
                        "status": "Open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    # Failure before any artifacts: skip_agent2 alone
    code = cli_mod.main(
        [
            "run",
            "--work-dir",
            str(work),
            "--product-line",
            "hc",
            "--source",
            str(raw),
            "--posture",
            "alpha",
            "--skip-agent2",
            "--out-dir",
            str(out),
        ]
    )
    assert code == 1
    # Early reject has no batch yet — out dir may be empty; ensure no crash and dir created
    assert out.is_dir()


def test_http_get_rejects_unsafe_run_id(tmp_path: Path):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bugfix_agent.http import create_app

    app = create_app(background=False)
    client = TestClient(app)
    r = client.get("/v1/runs/../../outside", params={"workDir": str(tmp_path)})
    assert r.status_code in (400, 404, 422)
