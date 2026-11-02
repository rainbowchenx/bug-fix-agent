---
name: defect-batch-prepare
description: Prepare a defect-batch via ingest → distill → rule screen → L1/L2/L3 cluster. Deterministic pipeline; do not freestyle screen rules.
profiles: defect-batch
---

# Defect Batch Prepare（Agent-1）

**形态**：本 Skill 描述 SOP；**筛池与 L1/L2 必须由代码管线执行**，禁止用模型「手跑」替代 R0–R3 / L1–L2。

## 边界

| 做 | 不做 |
|---|---|
| 拉取（MCP 准 / 爬虫备 / preloaded）→ `raw-defects` | 通读业务源码、根因、改码 |
| 蒸馏描述模板、测试模块 / 标题括注 | 读取 `所属模块` 等闭环字段 |
| 规则筛选 → `strict` 与旁路池 | 缺陷平台写操作 |
| L1→L2→L3 分簇与排序 → `defect-batch` | 推翻 R2 硬淘汰 |

权威规则：`docs/defect-input-analysis/_stage1-rules.md` + `docs/superpowers/specs/2026-10-30-defect-screen-cluster-design.md`。

## 流程

```text
Ingest (mcp|crawler|preloaded) → raw-defects
  → distill (0 LLM)
  → screen R0–R3 (0 LLM)
  → cluster L1/L2 (0 LLM) → L3 intent (heuristic or injected AI)
  → R5/R6 → validate → defect-batch.json
```

代码入口：

- `ingestRawDefects()` — `src/ingest`
- `prepareDefectBatch()` — `src/defect-batch`

## 业务 Skill 可叠加（profiles: defect-batch）

允许注入：模块别名、标题括注习惯、意图类目释义。  
**禁止**：用业务 skill 推翻 R2 / 绕过 `raw-defects` 边界。

## L3 意图

默认启发式分类器；可注入 `IntentClassifier` 做批处理 LLM。封闭枚举见 `INTENT_ENUM`（可后续冻结）。

## 产出契约

`defect-batch`：`schemaVersion`、`productLine`、`funnel`、`clusters[]`、`tickets[]`。  
输出后必须 `validateDefectBatch`；失败不得交给 Agent-2/3。
