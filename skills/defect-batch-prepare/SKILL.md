---
name: defect-batch-prepare
description: Prepares defect-batch JSON from raw defects via ingest, rule distill/screen, and L1→L2→L3 clustering. Use when running Agent-1, converting Excel/MCP defect exports, screening/clustering tickets, or validating defect-batch output—never freestyle R0–R3 or L1/L2 in the model.
profiles: defect-batch
---

# Defect Batch Prepare（Agent-1）

SOP only. **R0–R3 and L1/L2 run in code** (`prepareDefectBatch` / `runDefectBatchPrepare`). Do not re-implement screen rules in chat.

## When to use

- Building or refreshing a `defect-batch` for Agent-2/3
- Ingesting preloaded JSON / Excel exports (see `scripts/xlsx_to_raw_defects.py`)
- Checking funnel pools: `strict` / `locatable_only` / `needs_info` / `hard_reject` / `security` / `excluded`

## Do / Don't

| Do | Don't |
|---|---|
| Ingest → `raw-defects` → distill → screen → cluster → validate | Read `所属模块` or other closed-loop fields |
| Call code entrypoints below | Hand-run R2/R3 regexes in the model |
| Inject business skills for aliases / intent gloss only | Override hard rejects via skill text |

## Pipeline

```text
ingest (preloaded | mcp* | crawler*) → raw-defects
  → distill → screen R0–R3 → cluster L1/L2 + L3 intent → R5/R6
  → validateDefectBatch → defect-batch.json
```

\* mcp/crawler adapters are stubs until tool maps exist; use **preloaded**.

### Code entrypoints

```ts
import { runDefectBatchPrepare, prepareDefectBatch, validateDefectBatch } from "bugfix-agent";

const batch = await runDefectBatchPrepare({
  mode: "preloaded",
  productLine: "hc",
  posture: "alpha", // or "beta" (Open/New only)
  source: "./raw-defects.json",
});
```

## Excel → raw-defects

```bash
python3 skills/defect-batch-prepare/scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/export.xlsx \
  --product-line hc \
  --out raw-defects.json
```

Requires `openpyxl`. Column aliases: `缺陷ID`/`标题|缺陷标题`/`缺陷描述`/`缺陷状态`/`测试模块`/…

## Output contract

`defect-batch`: `schemaVersion`, `productLine`, `posture`, `funnel`, `clusters[]`, `tickets[]`.  
Fail closed: invalid batch must not go to Agent-2/3.

## References

- Rules: [reference.md](reference.md)
- Examples: [examples.md](examples.md)
- Stage1: `docs/defect-input-analysis/_stage1-rules.md`
- Funnel: `docs/superpowers/specs/2026-10-30-defect-screen-cluster-design.md`
