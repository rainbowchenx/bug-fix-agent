# SWE-bench Adapter Design

**Goal:** 用独立上层适配器在 SWE-bench 子集上跑现有 bugfix-agent，导出 `predictions.jsonl`，再交给官方 harness 打 Resolved%，拿能力基线。

## 解耦原则

| 层 | 职责 | 禁止 |
|----|------|------|
| 核心 `src/` | 通用编排、handlers 注入点 | 不出现 `instance_id` / SWE 类型 / predictions 格式 |
| `adapters/swe-bench/` | 数据映射、checkout、patch 交付、批跑 CLI | 不改 runner 控制流；不 import 核心私有实现细节以外的「SWE 专用」钩子 |

对接面（仅公共能力）：

- `runPipeline` / `createRunDir` / `writeInputDefects`
- `RunnerOptions.handlers`：`ensureRepo`、`deliverFix`、`resolveVerifyPlan`、`prepareRepo`（可选）
- `getDiffText` / `Defect` schema

核心**零 SWE 知识**。公司内部缺陷 adapter 可平行放在 `adapters/internal-bugs/`，共用同一套 handlers 模式。

## 数据流

```text
SWE instance.json(l)
    → mapToDefect()
    → writeInputDefects + runPipeline(handlers=sweHandlers)
    → deliverFix 写 model_patch
    → predictions.jsonl
    → (可选) swebench.harness.run_evaluation
```

## 模块

- `types.ts` — SWE 实例形状（仅 adapter 内）
- `map-instance.ts` — → `Defect` + request options
- `handlers.ts` — 组装 `ClusterHandlers`（checkout @ base_commit、patch deliver、pytest 启发式）
- `predictions.ts` — 追加 jsonl
- `run-batch.ts` — 批跑
- `cli.ts` — `tsx adapters/swe-bench/cli.ts ...`

## 非目标（本波）

- 不在本仓嵌入 Docker 官方评测
- 不改 GitLab deliver 默认路径
- 不做全量 Verified；默认 `--limit 20`
