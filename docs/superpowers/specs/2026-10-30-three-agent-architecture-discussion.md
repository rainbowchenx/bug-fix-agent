# 三 Agent 架构探讨 · 索引

> 日期：2026-10-30（2026-11-01：拆成三份专文）  
> 状态：**探讨中 / 非正式规格**——**不启动实现**。  
> 详文已拆开，本文只保留总览与链接。

相关基线：

- [报告型分析 Agent 设计](2026-10-23-report-agent-design.md)
- [报告型分析 Agent 决策备忘](2026-10-23-report-agent-decision-memo.md)
- [目标流水线设计](2026-10-22-target-pipeline-design.md)
- [缺陷单多轮筛选与分簇设计](2026-10-30-defect-screen-cluster-design.md)

---

## 专文

| 段 | 文档 | 状态 |
|---|---|---|
| **Agent-1** 缺陷批次准备 | [2026-10-30-agent1-defect-batch-discussion.md](2026-10-30-agent1-defect-batch-discussion.md) | **已收口**（Skill + 管线；MCP 拉取解耦；L1→L2→L3 分簇） |
| **Agent-2** 代码通读 | [2026-10-30-agent2-code-cartographer-discussion.md](2026-10-30-agent2-code-cartographer-discussion.md) | 探讨中（三形态框架；CodeGraph 跟 CLAUDE.md；按条匹配） |
| **Agent-3** 缺陷分析报告 | [2026-10-30-agent3-defect-analyst-discussion.md](2026-10-30-agent3-defect-analyst-discussion.md) | 探讨中（内容较薄，待深化） |

---

## 总览

```text
┌─ Agent-1 批次准备（Skill + 规则管线）─────────────────┐
│ Ingest(MCP|爬虫) → raw-defects → 蒸馏/筛选/分簇         │
│ 产出: defect-batch                                     │
└──────────────────────────┬────────────────────────────┘
                           │
┌─ Agent-2 代码通读 ────────────────────────────────────┐
│ 持 defect-batch；三形态；CLAUDE.md→CodeGraph；按条匹配 │
│ 产出: code-knowledge                                   │
└──────────────────────────┬────────────────────────────┘
                           │ ① + ②
┌─ Agent-3 分析报告 ────────────────────────────────────┐
│ 定位 → 根因 → 方案（不改码）→ analysis-report          │
└───────────────────────────────────────────────────────┘
```

原则：

1. 只传落盘 artifact，不传会话 transcript。  
2. 成本重心在 Agent-3；Agent-1 以规则为主。  
3. 全自动无审批断点。  
4. Orchestrator 为确定性代码；各段是可注入阶段，不是互聊 chatbot。  

---

## 跨段共识摘要

| 项 | 倾向 |
|---|---|
| 产品边界 | 止于分析报告（对齐 10-23）；改码/MR 下游 |
| SDD | 框架无关；`.claude` 为发现总线 |
| Agent-1 形态 | Skill + 管线，非独立长会话 Agent |
| Agent-2 CodeGraph | 用户仓内；跟 `CLAUDE.md` |
| Agent-2 匹配 | 按条；批次 ≤~30 |
| 可修文案 | 待 Agent-3 拍；折中见专文 |

---

## 跨段待拍板

| ID | 问题 | 归属 |
|---|---|---|
| Q-B | 可修/不可修 vs confidence+suggestedAction | Agent-3 |
| Q-D | 三份 artifact 最终 schema | 契约专文（未开） |
| Q-E | 同进程阶段 vs 分服务 | 索引级；1 已定 Skill+管线 |
| Q-F | 先正式规格再实现 | 当前：继续探讨 |

各段专属遗留见对应专文。

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 合稿初版 |
| 2026-11-01 | Agent-1 收口；Agent-2 补三形态/CodeGraph/按条匹配 |
| 2026-11-01 | **拆成 Agent-1 / 2 / 3 三份专文**；本稿改为索引 |
