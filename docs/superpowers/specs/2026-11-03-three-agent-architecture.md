# 三 Agent 正式架构（实现脚手架）

> 日期：2026-11-03  
> 状态：**实现中**（自探讨收口转入代码骨架）  
> 探讨基线：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md) · [Agent-1](2026-10-30-agent1-defect-batch-discussion.md) · [Agent-2](2026-10-30-agent2-code-cartographer-discussion.md) · [Agent-3](2026-10-30-agent3-defect-analyst-discussion.md)

---

## 1. 目标

在**不合并超级 Agent**的前提下，把松耦合工作流落到仓内目录与入口：

```text
validate → Agent-1 → validate → Agent-2 → validate → Agent-3 → validate
            defect-batch         code-knowledge        analysis-report
```

- **仅**落盘 artifact + zod 校验跨段；禁止跨 Agent 调内部函数 / 共享未落盘 transcript。  
- 旧 `pipeline` / `runs/runner` **保留**（既有 BugFix 双结局路径）；三 Agent 走 `src/workflow/`。  
- Agent-1 已实现（`src/defect-batch` + Skill）；本脚手架补契约、父编排、Agent-2/3 骨架。

---

## 2. 目录边界

| 路径 | 段 | 职责 |
|---|---|---|
| `src/ingest/` | Agent-1 内 | 拉取 → `raw-defects` |
| `src/defect-batch/` | Agent-1 | 蒸馏/筛选/分簇 → `defect-batch` |
| `src/code-knowledge/` | Agent-2 | 通读/匹配 → `code-knowledge`（骨架） |
| `src/defect-analyst/` | Agent-3 | 按条分析+patch → `analysis-report`（骨架） |
| `src/workflow/` | 父编排 | 串段 + 进出校验；**不**含业务规则 |
| `skills/defect-batch-prepare/` | Agent-1 SOP | 已有 |
| `skills/*`（后续） | Agent-2/3 | `profiles: cartography` / `analyze`/`fix` |

禁止：`workflow` 直接 import 各段内部 helper（只走公开 `run*` / `validate*`）。

---

## 3. Artifact 契约（v0.1.0 可演进）

| Artifact | 生产者 | 校验入口 | 消费者 |
|---|---|---|---|
| `raw-defects` | ingest | `RawDefectsFileSchema` | Agent-1 内部 |
| `defect-batch` | Agent-1 | `validateDefectBatch` | Agent-2、Agent-3 |
| `code-knowledge` | Agent-2 | `validateCodeKnowledge` | Agent-3 |
| `analysis-report` | Agent-3 | `validateAnalysisReport` | 人 / 下游 |

字段随实现加厚；`schemaVersion` 必填。校验失败 → **硬停**，不得带病下游。

---

## 4. 父工作流入参（骨架）

```ts
runThreeAgentWorkflow({
  workDir: string,
  productLine: string,
  posture?: "alpha" | "beta",
  // Agent-1
  ingest: { mode: "preloaded" | "mcp" | "crawler"; source?: string },
  // Agent-2 / 3（骨架阶段可 stub）
  openMr?: boolean,          // 默认 false
  skipAgent2?: boolean,      // 测试用
  skipAgent3?: boolean,
  handlers?: { agent2?; agent3? }, // 注入实现 / stub
})
```

落盘建议（Run 目录，后续接 store）：

```text
{workDir}/.bugfix-runs/{runId}/
  defect-batch.json
  code-knowledge.json
  analysis-report.json
```

---

## 5. 实现顺序（本 PR → 后续）

| 步 | 内容 | 本 PR |
|---|---|---|
| S0 | 目录 + zod 契约 + `runThreeAgentWorkflow` 门禁 | ✅ |
| S1 | Agent-1 已接入父工作流 | ✅ |
| S2 | Agent-2：bootstrap / map / match 子图 | 后续 |
| S3 | Agent-3：ticket_subgraph + openMr integrate | 后续 |
| S4 | HTTP/CLI 暴露三 Agent Run；旧 pipeline 并存 | 后续 |

---

## 6. 与旧路径关系

| 路径 | 用途 |
|---|---|
| `POST /v1/runs` + `runPipeline` | 既有簇级 BugFix（GREEN→MR） |
| `runThreeAgentWorkflow` | 新主路径：批次准备 → 通读 → 按条分析/patch |

迁移策略：先并行；Agent-3 可复用 `pipeline/analyze|implement|deliver` **语义**，但编排改为按条 + 独立子图，不把 Cartographer 状态混进旧 `ClusterState`。

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-11-03 | 自探讨收口转入正式架构脚手架 |
