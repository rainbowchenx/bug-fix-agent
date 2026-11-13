import json
from pathlib import Path

from bugfix_platform.agents.analyst import route_ticket
from bugfix_contracts import (
    ANALYSIS_REPORT_SCHEMA_VERSION,
    CODE_KNOWLEDGE_SCHEMA_VERSION,
    BatchTicket,
    DefectCodeMatch,
)
from bugfix_platform.workflow import run_three_agent_workflow
from tests.helpers import defect_batch_from_hc1


def test_workflow_e2e(tmp_path: Path):
    from tests.helpers import ensure_git_repo

    work = ensure_git_repo(tmp_path / "mini")
    (work / "src").mkdir(parents=True, exist_ok=True)
    (work / "package.json").write_text(
        json.dumps({"name": "mini-hc", "version": "0.0.1", "dependencies": {"electron": "30.0.0"}}),
        encoding="utf-8",
    )
    (work / "CLAUDE.md").write_text("# Mini\nUse CodeGraph for search.\n", encoding="utf-8")
    (work / "src" / "preview-player.ts").write_text("export const preview = 1;\n", encoding="utf-8")
    (work / "src" / "回放.ts").write_text("export {}\n", encoding="utf-8")
    (work / "src" / "检索.ts").write_text("export {}\n", encoding="utf-8")

    result = run_three_agent_workflow(
        work_dir=work,
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
        cartography_mode="heuristic",
        open_mr=False,
        cartography_profile="electron_node",
    )
    assert result.ok is True
    assert result.artifacts.defect_batch is not None
    assert result.artifacts.defect_batch.funnel["total"] == 50
    assert result.artifacts.code_knowledge is not None
    assert result.artifacts.code_knowledge.schemaVersion == CODE_KNOWLEDGE_SCHEMA_VERSION
    assert result.artifacts.code_knowledge.cartographyProfile == "electron_node"
    assert result.artifacts.analysis_report is not None
    assert result.artifacts.analysis_report.schemaVersion == ANALYSIS_REPORT_SCHEMA_VERSION
    assert result.artifacts.analysis_report.tickets
    outcomes = {t.outcome for t in result.artifacts.analysis_report.tickets}
    assert outcomes & {"plan_only", "unlocalized", "needs_ticket_info"}


def test_workflow_hard_stop_invalid_agent2():
    def bad_agent2(**_kwargs):
        return {"broken": True}

    result = run_three_agent_workflow(
        work_dir="/tmp/x",
        product_line="hc",
        posture="alpha",
        defect_batch=defect_batch_from_hc1(),
        analyze_mode="heuristic",
        cartography_mode="heuristic",
        agent2=bad_agent2,
    )
    assert result.ok is False
    assert result.stage == "agent2"
    assert "code-knowledge" in (result.error or "")


def test_router_outcomes():
    base = BatchTicket(
        defectId="1",
        title="t",
        pool="strict",
        expectQuality="explicit",
    )
    r1 = route_ticket(base.model_copy(update={"pool": "needs_info", "expected": ""}), None)
    assert r1["outcome"] == "needs_ticket_info"

    r2 = route_ticket(
        base,
        DefectCodeMatch(defectId="1", candidates=[], confidence="low"),
    )
    assert r2["outcome"] == "unlocalized"

    r3 = route_ticket(
        base.model_copy(update={"pool": "locatable_only"}),
        DefectCodeMatch(
            defectId="1",
            candidates=[{"repoPath": ".", "path": "src/a.ts", "why": "hit", "source": "heuristic"}],
            confidence="medium",
        ),
    )
    assert r3["outcome"] == "plan_only"
    assert r3["proposedFix"]["targetFiles"][0] == "src/a.ts"
    # 纯启发式 soft-start 不得把 medium 带进 Agent-3 路由。
    assert r3["confidence"] == "low"
    assert "heuristic-only" in r3["localization"]["notes"]

    r4 = route_ticket(
        base,
        DefectCodeMatch(
            defectId="1",
            candidates=[{"repoPath": ".", "path": "src/b.ts", "why": "sdk", "source": "grep"}],
            confidence="high",
        ),
    )
    assert r4["outcome"] == "plan_only"
    assert r4["confidence"] == "medium"  # high 封顶 medium，非启发式可保留
