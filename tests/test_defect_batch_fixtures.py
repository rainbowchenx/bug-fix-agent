from pathlib import Path

from bugfix_agent.defect_batch import run_defect_batch_prepare

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "test" / "fixtures" / "defect-batch"


def test_hc1_alpha_funnel():
    batch = run_defect_batch_prepare(
        product_line="hc",
        posture="alpha",
        source=FX / "hc1-raw.json",
    )
    assert batch.funnel["total"] == 50
    assert batch.funnel["excluded"] > 0
    assert len(batch.tickets) == 50
    for c in batch.clusters:
        for did in c.defectIds:
            t = next(x for x in batch.tickets if x.defectId == did)
            assert t.pool == "strict"


def test_hcp_xunjian_beta_functional_open():
    batch = run_defect_batch_prepare(
        product_line="hcp",
        posture="beta",
        source=FX / "hcp-xunjian-raw.json",
    )
    assert batch.funnel["total"] == 30
    assert batch.funnel["security"] > 0
    functional = [t for t in batch.tickets if t.pool not in ("excluded", "security")]
    assert functional
    assert all((t.status or "").lower() in {"open", "new"} for t in functional)


def test_hitools_sample():
    batch = run_defect_batch_prepare(
        product_line="hitools",
        posture="alpha",
        source=FX / "hitools-sample80-raw.json",
    )
    assert batch.funnel["total"] == 80
    assert batch.schemaVersion == "0.1.0"
