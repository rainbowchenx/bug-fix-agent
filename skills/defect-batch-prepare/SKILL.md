---
name: defect-batch-prepare
description: Prepares defect-batch JSON from raw defects via ingest, rule distill/screen, and L1→L2→L3 clustering (Python). Use when running Agent-1, converting Excel/MCP defect exports, screening/clustering tickets, or validating defect-batch output—never freestyle R0–R3 or L1/L2 in the model.
profiles: defect-batch
---

# Defect Batch Prepare（Agent-1 · Python）

SOP only. **R0–R3 and L1/L2 run in code** (`prepare_defect_batch` / `run_defect_batch_prepare`). Do not re-implement screen rules in chat.

## When to use

- Building or refreshing a `defect-batch` for Agent-2/3
- Ingesting preloaded JSON / Excel exports (see `bugfix_agent/scripts/xlsx_to_raw_defects.py`)
- Checking funnel pools: `strict` / `locatable_only` / `needs_info` / `hard_reject` / `security` / `excluded`

## Do / Don't

| Do | Don't |
|---|---|
| Ingest → `raw-defects` → distill → screen → cluster → validate | Read `所属模块` or other closed-loop fields |
| Call Python entrypoints below | Hand-run R2/R3 regexes in the model |
| Inject business skills for aliases / intent gloss only | Override hard rejects via skill text |

## Pipeline

```text
ingest (preloaded | mcp* | crawler*) → raw-defects
  → distill → screen R0–R3 → cluster L1/L2 + L3 intent → R5/R6
  → validate_defect_batch → defect-batch.json
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
```

## Excel / CSV → raw-defects

```bash
# Chinese Excel export
python3 bugfix_agent/scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/export.xlsx \
  --product-line hc \
  --out raw-defects.json

# English camelCase CSV（缺陷拉取/脱敏/*.csv；平台拼写 describle）
python3 bugfix_agent/scripts/csv_to_raw_defects.py \
  --csv 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --product-line ax-hybrid \
  --out 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.raw-defects.json
```

Excel 需要 `openpyxl`。字段映射见 `缺陷拉取/脱敏/README.md`。

## Output contract

See `docs/contracts/v0.1/` (Pydantic SSOT: `bugfix_agent/contracts/`).

## References

- Rules: [reference.md](reference.md)
- Examples: [examples.md](examples.md)
- Stage1: `docs/defect-input-analysis/_stage1-rules.md`
