---
name: defect-batch-prepare
description: Prepares defect-batch JSON from raw defects via ingest, rule distill/screen, L1→L2 clustering, then an intent-review pass that reads original ticket text and corrects L3 intent (and match-pool mistakes). Use when converting Excel/CSV/JSON defect exports, screening/clustering tickets, or validating defect-batch output. Never freestyle R0–R3 or L1/L2 in chat. After success, hand off defect-batch.json to bugfix-agent run.
profiles: defect-batch
---

# Defect Batch Prepare

SOP. 本 skill + 规则管线产出 `defect-batch.json`。筛池 / L1 / L2 必须走代码；**描述五花八门的意图理解放在规则跑完之后的复核步**。

## When to use

- 把导出的缺陷列表做成 `defect-batch`
- 检查漏斗：`strict` / `locatable_only` / `needs_info` / `hard_reject` / `security` / `excluded` / `duplicate`
- 规则分簇之后，按原文判断 `intent`（以及功能池是否放错）并回写

## Do / Don't

| Do | Don't |
|---|---|
| 先跑 `prepare-batch`，再读原文做意图复核 | 在对话里重写 R0–R3 正则或 L1/L2 取值 |
| 复核时对照**原始描述**（产物里已丢掉长描述） | 只看蒸馏切片就下结论 |
| 用 `apply-review` 回写，让脚本重建簇并校验 | 手改 `clusterId` / `clusters[]` / `funnel` |
| 只在匹配池内调整；意图必须落在封闭枚举 | 推翻 `hard_reject` / `security` / `excluded` / `duplicate` |
| 注入业务 skill 只解释模块别名、意图口径 | 读 `所属模块`；发明新的 intent 标签 |

## Pipeline

```text
ingest (preloaded) → raw-defects
  → distill → screen R0–R3 → cluster L1/L2 + heuristic L3 → R5/R6
  → validate_defect_batch → defect-batch.json          # 规则层，0 LLM
  → 读原文，按意图复核分类 → adjustments.json
  → apply-review → 重建簇 + 再校验 → defect-batch.json  # 本 skill 的理解层
```

mcp/crawler 仍为 stub；用 **preloaded**（CSV / JSON / xlsx 派生）。

### 1）规则层（必须用脚本）

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source path/to/export.csv \
  --posture beta \
  --out defect-batch.json
```

```python
from bugfix_agent import run_defect_batch_prepare

batch = run_defect_batch_prepare(
    product_line="hc",
    posture="alpha",
    source="./raw-defects.json",
)
```

**R0–R3 and L1/L2 run in code.** Do not re-implement screen rules in chat.

### 2）意图复核（本 skill 要做的理解，不是脚本替代品）

规则只做硬分流和结构键。启发式 L3 只是关键词先验。描述不规范时，**必须读原始单**，判断分类对不对，再调整。

对照材料：

- `defect-batch.json` 里的 `title` / `observed` / `expected` / `steps` / `pool` / `intent*`
- 原始导出（CSV/JSON）里的完整描述——批次产物**不再带**长 `description`

优先看这些票（不必全量死抠旁路池）：

1. `intent` 为 `unclear`，或 `intentConfidence=low` / `intentSource` ∈ `heuristic` / `field_fallback`
2. `locatable_only`、`needs_info`（常常是蒸馏没抽出预期，原文其实能读懂）
3. 标题/原文与当前 `intent` 明显打架（例如满篇「未翻译」却标成 `logic`）

对每张要改的票，写清：**原文在说什么 → 应属哪类意图 → 是否还应留在当前功能池**。

封闭意图枚举（不可自造）：

`ui_layout` · `i18n` · `logic` · `data_wrong` · `perf` · `compat` · `config` · `security_scan` · `crash` · `unclear`

可改：

- `intent`（及 rationale / confidence）；回写后 `intentSource` 必为 `ai`
- 匹配池之间的 `pool`：`strict` ↔ `locatable_only` ↔ `needs_info`
- 升入 `strict` 时必须带 `expectQuality=explicit|inferred`

不可改：

- `hard_reject` / `security` / `excluded` / `duplicate`（进或出都不行）
- `testModule` / `titleTag`（L1/L2 仍走规则）

落盘 `review.json`：

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

回写（脚本重建 `clusterId` / `clusters[]` / `funnel` 并校验）：

```bash
bugfix-agent apply-review \
  --batch defect-batch.json \
  --overrides review.json \
  --out defect-batch.json
```

没有需要改的票：不要空跑；直接把规则产物交给后续步骤。

## Platform CSV / Excel

平台导出 CSV 可直接作为 `--source`。xlsx：

```bash
python3 bugfix_agent/scripts/xlsx_to_raw_defects.py \
  --xlsx path/to/export.xlsx --product-line hc --out raw-defects.json
```

字段映射 SSOT：`bugfix_agent/ingest/field_map.py`（含平台拼写 `describle`）。xlsx 需 `openpyxl`。

## Output contract

See `docs/contracts/v0.1/defect-batch-guide.md` (Pydantic SSOT: `bugfix_agent/contracts/`).

## References

- Rules: [reference.md](reference.md)
- Examples: [examples.md](examples.md)
- Stage1: `docs/defect-input-analysis/_stage1-rules.md`
