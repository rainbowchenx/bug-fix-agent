# 跨 Agent 数据契约 v0.1（审阅稿）

> 日期：2026-11-03 · **供评估**：字段可改，改完需同步 Pydantic（`bugfix_agent/contracts/`）  
> 实现语言：**Python**（不再使用 JS 三 Agent 路径）  
> 依据：三 Agent 探讨收口 + [正式架构](../../superpowers/specs/2026-11-03-three-agent-architecture.md)

## 耦合规则

```text
Agent-1 ──defect-batch──► Agent-2 ──code-knowledge──► Agent-3 ──analysis-report──► 人/下游
                ▲                      ▲
                └──── 仅 artifact + zod 校验；禁止跨包调内部函数 / 共享 transcript
```

| Artifact | 生产者 | 消费者 | Schema |
|---|---|---|---|
| `raw-defects`（入口） | 平台 CSV / Excel / JSON | Agent-1 | [raw-defects-entry.md](raw-defects-entry.md) |
| `defect-batch` | Agent-1 | Agent-2、Agent-3 | [defect-batch.md](defect-batch.md) |
| `code-knowledge` | Agent-2 | Agent-3 | [code-knowledge.md](code-knowledge.md) |
| `analysis-report` | Agent-3 | 人 / 下游 | [analysis-report.md](analysis-report.md) |

代码 SSOT：`bugfix_agent/contracts/*`。样例：`samples/*.json`。

## 匹配池（Agent-2 / 3 默认）

`strict` | `locatable_only` | `needs_info`  
（`hard_reject` / `security` / `excluded` 默认不进入匹配与分析）

## 包边界（Python）

| 包 | 路径 | 依赖 |
|---|---|---|
| contracts | `bugfix_agent/contracts` | pydantic |
| defect_batch (Agent-1) | `bugfix_agent/defect_batch` | contracts + ingest |
| cartographer (Agent-2) | `bugfix_agent/agents/cartographer` | contracts + fs |
| analyst (Agent-3) | `bugfix_agent/agents/analyst` | contracts only |
| workflow | `bugfix_agent/workflow` | 只调各包公开 `run_*` + `validate_*` |

## 审阅时请关注

1. `code-knowledge.defectCodeMatches` 是否够 Agent-3 软起点  
2. `TicketOutcome` 枚举与 blockers / proposedFix 互斥是否合理  
3. `partial` / `integrateMode` / `verifyStatus` 默认语义  
4. 是否缺字段（多子仓 `repoPath`、DR/DS、confidence 粒度过粗等）
