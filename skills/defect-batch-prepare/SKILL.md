---
name: defect-batch-prepare
description: Prepares defect-batch JSON from raw defects via ingest, rule distill/screen, and L1→L2→L3 clustering (Python). Use when running Agent-1 outside LangGraph, converting Excel/MCP defect exports, screening/clustering tickets, or validating defect-batch output—never freestyle R0–R3 or L1/L2 in the model. After success, hand off defect-batch.json to bugfix-agent run (Agent-2→3).
profiles: defect-batch
---

# Defect Batch Prepare（Agent-1 · 图外）

SOP only. **Agent-1 不在 LangGraph 父图内**：由本 skill + Claude Code（或 `prepare-batch` CLI）产出 `defect-batch.json`，再交给 Agent-2→3。

**R0–R3 and L1/L2 run in code** (`prepare_defect_batch` / `run_defect_batch_prepare`). Do not re-implement screen rules in chat.

## When to use

- Building or refreshing a `defect-batch` for Agent-2/3
- Ingesting preloaded JSON / Excel exports (see `bugfix_agent/scripts/xlsx_to_raw_defects.py`)
- Checking funnel pools: `strict` / `locatable_only` / `needs_info` / `hard_reject` / `security` / `excluded` / `duplicate`

## Do / Don't

| Do | Don't |
|---|---|
| Ingest → `raw-defects` → distill → screen → cluster → validate | Read `所属模块` or other closed-loop fields |
| Call Python entrypoints / `prepare-batch` below | Hand-run R2/R3 regexes in the model |
| Hand off `defect-batch.json` to `bugfix-agent run --defect-batch` | Expect LangGraph to ingest raw CSV/JSON for Agent-1 |
| Inject business skills for aliases / intent gloss only | Override hard rejects via skill text |

## Pipeline

```text
ingest (preloaded | mcp* | crawler*) → raw-defects
  → distill → screen R0–R3 → cluster L1/L2 + L3 intent → R5/R6
  → validate_defect_batch → defect-batch.json
  → (handoff) bugfix-agent run --defect-batch …   # LangGraph Agent-2→3
```

\* mcp/crawler adapters are stubs; use **preloaded**.

### Code entrypoints

```python
from bugfix_agent import run_defect_batch_prepare, run_three_agent_workflow

batch = run_defect_batch_prepare(
    product_line="hc",
    posture="alpha",
    source="./raw-defects.json",
)

# LangGraph 只吃 defect-batch，不再吃 raw source
result = run_three_agent_workflow(
    work_dir="./repos",
    product_line="hc",
    defect_batch=batch,
    posture="alpha",
)
```

## Platform CSV / Excel → raw-defects

平台导出 CSV（`缺陷拉取/脱敏/*.csv`，列名 `defectTitle` / `describle` / …）可直接作为 `--source`：

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --posture beta \
  --out defect-batch.json

bugfix-agent run \
  --work-dir ./repos \
  --product-line hc \
  --defect-batch defect-batch.json \
  --analyze-mode heuristic \
  --out-dir /tmp/out
```

```bash
python3 bugfix_agent/scripts/csv_to_raw_defects.py \
  --csv path/to/export.csv --product-line hc --out raw-defects.json

python3 bugfix_agent/scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/export.xlsx --product-line hc --out raw-defects.json
```

字段映射 SSOT：`bugfix_agent/ingest/field_map.py`（含平台拼写 `describle`）。xlsx 需 `openpyxl`。

## Output contract

See `docs/contracts/v0.1/` (Pydantic SSOT: `bugfix_agent/contracts/`).

## References

- Rules: [reference.md](reference.md)
- Examples: [examples.md](examples.md)
- Stage1: `docs/defect-input-analysis/_stage1-rules.md`
