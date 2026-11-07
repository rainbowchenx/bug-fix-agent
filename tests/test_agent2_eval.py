"""Agent-2 evaluation rubric + scorer."""

from __future__ import annotations

import json
from pathlib import Path

from bugfix_agent.agents.cartographer import run_cartographer
from bugfix_agent.cli import main as cli_main
from bugfix_agent.defect_batch import run_defect_batch_prepare
from bugfix_agent.evals.agent2 import load_gold, score_code_knowledge

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "test" / "fixtures" / "agent2-eval"


def test_mini_fixture_eval_passes():
    work = FX / "mini-repo"
    batch = run_defect_batch_prepare(
        product_line="sample",
        source=FX / "raw-defects.json",
        posture="alpha",
    )
    knowledge = run_cartographer(
        work_dir=work,
        defect_batch=batch,
        cartography_mode="heuristic",
    )
    report = score_code_knowledge(
        work_dir=work,
        knowledge=knowledge,
        gold=FX / "gold.json",
    )
    assert report.schemaValid is True
    assert report.pathsExistRate == 1.0
    assert report.candidateCapOk is True
    assert report.negativeAccuracy == 1.0
    assert report.hitAt3 is not None and report.hitAt3 >= 0.7
    assert report.passed is True


def test_cli_eval_agent2(tmp_path: Path):
    out = tmp_path / "report.json"
    code = cli_main(
        [
            "eval-agent2",
            "--work-dir",
            str(FX / "mini-repo"),
            "--source",
            str(FX / "raw-defects.json"),
            "--gold",
            str(FX / "gold.json"),
            "--product-line",
            "sample",
            "--posture",
            "alpha",
            "--cartography-mode",
            "heuristic",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["dataset"] == "agent2-mini-fixture"


def test_gold_loader_defaults():
    gold = load_gold(
        {
            "name": "x",
            "tickets": [{"defectId": "1", "expectEmpty": True}],
        }
    )
    assert gold.gates.minHitAt3 == 0.7
    assert gold.tickets[0].expectEmpty is True
