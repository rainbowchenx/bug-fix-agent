# 三 Agent 架构探讨 · 索引

> 日期：2026-10-30  
> **最近修订：2026-11-02 08:57（Asia/Shanghai）**  
> 状态：**主路径探讨已收口**（非正式规格）——**仍不启动实现**。  
> 详文已拆开；本文 = 总览 + 跨段约定 + **收口摘要**。

相关基线（Agent-3 尤须对照，完整表见 [Agent-3 §1.1–§1.2](2026-10-30-agent3-defect-analyst-discussion.md)）：

- [报告型分析 Agent 设计](2026-10-23-report-agent-design.md) · [决策备忘](2026-10-23-report-agent-decision-memo.md)
- [目标流水线设计](2026-10-22-target-pipeline-design.md) · [环境适配与降级](2026-10-22-environment-adapter-and-capability-degradation.md)
- [缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)
- [实现缺口分析](2026-10-17-implementation-gap-analysis-and-roadmap.md)
- [缺陷单多轮筛选与分簇设计](2026-10-30-defect-screen-cluster-design.md)
- 调研：[SOTA](../../research/2026-10-14-sota-bugfix-agent-survey.md) · [Seer](../../research/2026-10-14-sentry-seer-autofix-deep-dive.md) · [WorkBuddy](../../research/2026-10-15-workbuddy-bugfix-expert-research.md)
- 旧仓对照：`aiservice-for-monitor`（待读仓权限后补深潜，见 Agent-3 §1.2 / E6）

---

## 0. 探讨收口总览（2026-11-02）

三个 Agent **主路径已拍清**；可进入「正式规格 / 契约 / 实现」前的待命。JSON schema 终版、样本仓特化、旧仓源码深潜等 **不挡收口**。

| 段 | 一句话 | 专文 | 状态 |
|---|---|---|---|
| **Agent-1** | MCP（准）/爬虫（备）拉取解耦 → 规则蒸馏筛选 → L1 模块→L2 括注→L3 AI 意图分簇 → `defect-batch` | [专文](2026-10-30-agent1-defect-batch-discussion.md) · [漏斗](2026-10-30-defect-screen-cluster-design.md) | **已收口**（Skill + 管线，非重 Agent） |
| **Agent-2** | 通读 workDir（可多子仓）→ 三形态框架 + SDD/DR·DS + CodeGraph 按条匹配 → `code-knowledge` | [专文](2026-10-30-agent2-code-cartographer-discussion.md) | **主路径收口**（A 全确认；C 除 C2/C3/C4 与 JSON 终版） |
| **Agent-3** | 按条：定位/根因/方案/（可行动则）patch；每票完整报告 + outcome 分类；`openMr` 开关 | [专文](2026-10-30-agent3-defect-analyst-discussion.md) | **D 组收口** |

### 端到端（收口形态）

```text
┌─ Agent-1 批次准备 ────────────────────────────────────┐
│ Ingest → raw-defects → 蒸馏/筛选/分簇 → defect-batch   │
└──────────────────────────┬────────────────────────────┘
                           │ 仅 artifact + 校验
┌─ Agent-2 代码通读 ────────────────────────────────────┐
│ defect-batch → 架构/SDD/匹配 → code-knowledge          │
└──────────────────────────┬────────────────────────────┘
                           │ 仅 artifact + 校验
┌─ Agent-3 分析 + 按条 patch ───────────────────────────┐
│ 每票完整报告（单信息/根因/方案 或 分类阻断）           │
│ + 可选 patch；openMr？→ 并行本地提交→合冲突→单一 MR    │
└───────────────────────────────────────────────────────┘
```

### 跨段硬约定（已确认，不再讨论）

1. **松耦合工作流**：同仓可放，不合并超级 Agent；不共享会话 transcript。  
2. **只传落盘 artifact** + 进出**确定性脚本校验**（schema 终版随实现，Q-D）。  
3. **三端均可注入业务 Skill**（`defect-batch` / `cartography` / `analyze|fix`）。  
4. **全自动无审批断点**（不抄 Seer stopping_point）。  
5. 对照 SOTA/Seer/WorkBuddy：**学阶段产物、IRON LAW、scope lock、确定性交付**；Agent-3 **不强制本机 GREEN**（D3/D5）。

### 明确延后（不挡收口）

| 项 | 说明 |
|---|---|
| Q-D / E1 | 三份 artifact JSON 终版 |
| Agent-2 C2/C3/C4、B1–B7 | batch 形状/簇 ID/字段齐套；SDD 名单；三形态指纹等 |
| Agent-3 E 组 | 多子仓 worktree 细节；多样本选优；Reviewer |
| E6 aiservice | 私有仓深潜（本环境暂无读权限；GitHub 授权已拒） |
| Q-F | 正式规格文 vs 直接实现——产品另拍 |

---

## 专文状态

| 段 | 文档 | 状态 |
|---|---|---|
| **Agent-1** | [agent1](2026-10-30-agent1-defect-batch-discussion.md) | **已收口** |
| **Agent-2** | [agent2](2026-10-30-agent2-code-cartographer-discussion.md) | **主路径收口** |
| **Agent-3** | [agent3](2026-10-30-agent3-defect-analyst-discussion.md) | **D 组收口** |

---

## 跨段：工作流 + 松耦合（已确认）

**形态**：三个 Agent 以**工作流**串联，可同仓实现，但必须**松耦合**。

| 项 | 约定 |
|---|---|
| 耦合面 | **仅**稳定 I/O artifact |
| 禁止 | 跨 Agent 调内部函数、共享未落盘上下文、合并超级节点 |
| 编排 | 父图：校验 → Agent-N → 校验 → 下一步；各段自洽子图/管线 |
| 同仓 | monorepo 允许；边界按契约 |

```text
        ┌─ validate_in ──► Agent-1 ──► validate_out ─┐
        │         defect-batch                         │
workflow┤  validate_in ──► Agent-2 ──► validate_out ─┤
        │         code-knowledge                       │
        └─ validate_in ──► Agent-3 ──► validate_out ──► analysis-report
```

校验失败 → 硬停该步，不得带病下游。

---

## 跨段：契约与固定脚本校验（已确认）

| Artifact | 生产者 | 消费者 |
|---|---|---|
| `raw-defects` | Agent-1 Ingest（内部） | Agent-1 后续 |
| `defect-batch` | Agent-1 | Agent-2、Agent-3 |
| `code-knowledge` | Agent-2 | Agent-3 |
| `analysis-report` | Agent-3 | 人 / 下游 |

规则：输入前/输出后确定性校验；`schemaVersion`；终版不急（随实现）。

---

## 跨段：业务特性 Skill 注入（已确认）

| 项 | 约定 |
|---|---|
| 谁可注 | Agent-1 / 2 / 3 全部 |
| 来源 | Run options → `.bugfix/skills` → 仓内 `.claude/skills` → 段内置 |
| `profiles` | `defect-batch` / `cartography` / `analyze`（+ `fix`） |
| 边界 | 不替代筛池硬规则与 schema 校验 |

---

## 跨段共识摘要（收口版）

| 项 | 决定 |
|---|---|
| 集成 | 工作流 + 松耦合；仅契约 I/O |
| Agent-1 | Skill + 规则管线；MCP 拉取解耦；三层分簇 |
| Agent-2 | LangGraph + Claude Agent SDK；CodeGraph 跟 `CLAUDE.md`；匹配池含 strict+locatable+needs_info；无条数硬限；可多子仓 |
| Agent-3 | 分析+根因+方案+patch；每票完整报告与 `outcome` 分类；不强制本机验证；`openMr` 默认 off，开则本地集成单 MR |
| 产品边界 vs 10-23 | 报告仍核心；**额外可出 patch / 可选 MR**（非纯 BOUND-1） |
| 对照调研 | SOTA/Seer/WorkBuddy 已挂 Agent-3 §1.2；aiservice 待读仓 |

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 合稿初版 |
| 2026-11-01 | 拆三专文；松耦合；业务 Skill；Agent-1/2 推进 |
| 2026-11-01～02 | Agent-2 A/C；Agent-3 D 组；SOTA 对照表 |
| 2026-11-02 08:57 Asia/Shanghai | **三 Agent 主路径探讨收口总览**；更新跨段共识与延后清单 |
