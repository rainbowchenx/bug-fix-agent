---
name: defect-batch-prepare
description: Prepares defect-batch.json from exported defect lists (CSV, Excel, or JSON) by running the rule funnel, then rereading original ticket text to correct intent and match-pool placement. Use this skill whenever the user asks to 筛选, 分簇, 分类, or 复核缺陷单; convert a 缺陷列表 or 平台导出; run prepare-batch; build or validate defect-batch; or check whether tickets landed in the right pool or intent—even if they do not name this skill.
compatibility: Requires Python 3.11+, bugfix-agent CLI on PATH, and openpyxl when the source is .xlsx.
metadata:
  profiles: defect-batch
---

# Defect Batch Prepare

Turn an exported defect list into a validated `defect-batch.json`.

Screening and L1/L2 keys run in code so the same export yields the same funnel. Ticket descriptions are too irregular for those rules, so after the script finishes, reread the original text and correct intent (and match-pool mistakes).

## Workflow

```text
export → prepare-batch → defect-batch.json
       → reread originals → review.json → apply-review → defect-batch.json
```

CSV and JSON go straight to `prepare-batch`. For `.xlsx`, convert with the script bundled in this skill (needs `openpyxl`):

```bash
python scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/export.xlsx --product-line hc --out raw-defects.json
```

mcp/crawler ingest is still stubbed; use a preloaded file.

### 1. Rule funnel

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source path/to/export.csv \
  --posture beta \
  --out defect-batch.json
```

Do not re-implement R0–R3 or L1/L2 in chat. Those rules encode CVE/SCA, status posture, and module/tag parsing; a one-off rewrite will drift from the contract.

Pool meanings, posture, and CSV quirks: [references/reference.md](references/reference.md).

### 2. Intent review

The batch drops the long `description`. Heuristic L3 only matches keywords, so `unclear`, low confidence, `locatable_only`, and `needs_info` often mean "the template did not parse", not "the reporter said nothing". Read the original export next to `title` / `observed` / `expected` / `steps`.

For each change, write what the reporter meant, which closed intent it is, and whether it still belongs in the current match pool.

Closed intent set: `ui_layout` · `i18n` · `logic` · `data_wrong` · `perf` · `compat` · `config` · `security_scan` · `crash` · `unclear`

Safe to change: `intent` (then `intentSource` becomes `ai`), and `pool` among `strict` / `locatable_only` / `needs_info`. Promoting into `strict` needs `expectQuality` of `explicit` or `inferred`.

Leave `hard_reject` / `security` / `excluded` / `duplicate` alone — those are safety and status gates, not language understanding. Leave `testModule` / `titleTag` to the rules so `所属模块` never becomes a path. Do not hand-edit `clusterId` / `clusters[]` / `funnel`; `apply-review` rebuilds them so the file still validates.

Write only the tickets you are changing:

```json
{
  "adjustments": [
    {
      "defectId": "PJ-123",
      "intent": "ui_layout",
      "intentConfidence": "high",
      "intentRationale": "标题与实际结果都是按钮偏移/遮挡，不是逻辑错误",
      "pool": "strict",
      "expectQuality": "inferred"
    }
  ]
}
```

```bash
bugfix-agent apply-review \
  --batch defect-batch.json \
  --overrides review.json \
  --out defect-batch.json
```

If nothing should change, skip `apply-review` and hand off the rule output.

Command variants: [references/examples.md](references/examples.md). Output shape: `docs/contracts/v0.1/defect-batch-guide.md`.
