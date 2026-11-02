# 三 Agent 架构探讨 · 索引

> 日期：2026-10-30  
> **最近修订：2026-11-02 08:42（Asia/Shanghai）**  
> 状态：**探讨中 / 非正式规格**——**不启动实现**。  
> 详文已拆开，本文只保留总览与跨段约定。

相关基线（**Agent-3 尤须对照**，完整表见 [Agent-3 §1.1](2026-10-30-agent3-defect-analyst-discussion.md)）：

- [报告型分析 Agent 设计](2026-10-23-report-agent-design.md) · [决策备忘](2026-10-23-report-agent-decision-memo.md)
- [目标流水线设计](2026-10-22-target-pipeline-design.md) · [环境适配与降级](2026-10-22-environment-adapter-and-capability-degradation.md)
- [缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)
- [实现缺口分析](2026-10-17-implementation-gap-analysis-and-roadmap.md)
- [缺陷单多轮筛选与分簇设计](2026-10-30-defect-screen-cluster-design.md)
- 调研：[SOTA](../../research/2026-10-14-sota-bugfix-agent-survey.md) · [Seer](../../research/2026-10-14-sentry-seer-autofix-deep-dive.md) · [WorkBuddy](../../research/2026-10-15-workbuddy-bugfix-expert-research.md)

---

## 专文

| 段 | 文档 | 状态 |
|---|---|---|
| **Agent-1** 缺陷批次准备 | [2026-10-30-agent1-defect-batch-discussion.md](2026-10-30-agent1-defect-batch-discussion.md) | **已收口**（Skill + 管线；MCP 拉取解耦；L1→L2→L3 分簇） |
| **Agent-2** 代码通读 | [2026-10-30-agent2-code-cartographer-discussion.md](2026-10-30-agent2-code-cartographer-discussion.md) | 主路径 + A/C（除 C2/C3/C4）已收口 |
| **Agent-3** 分析与按条 patch | [2026-10-30-agent3-defect-analyst-discussion.md](2026-10-30-agent3-defect-analyst-discussion.md) | 每票完整报告+结局分类（D2）；分析+patch；不强制本机验证；D4/D6–D10 待拍 |

---

## 跨段：工作流 + 松耦合（已确认）

**形态**：三个 Agent 以**工作流**串联，可同仓实现，但必须**松耦合**——**不要**合并成单一巨图/共享可变会话状态。

| 项 | 约定 |
|---|---|
| 耦合面 | **仅**约定稳定的输入/输出 artifact 格式 |
| 禁止 | 跨 Agent 直接调内部函数、共享未落盘上下文、合并成一个「超级 Agent」节点 |
| 编排 | 外层工作流（如 LangGraph **父图**只做：校验 → 调 Agent-N → 校验 → 下一步）；各 Agent **自洽**（可有自己的子图/管线） |
| 同仓 | 允许 monorepo 多包/多目录；逻辑边界按契约，不按「图绑死」 |

```text
        ┌─ validate_in ──► Agent-1 ──► validate_out ─┐
        │         defect-batch                         │
workflow┤                                              │
        │  validate_in ──► Agent-2 ──► validate_out ─┤
        │         code-knowledge                       │
        │                                              │
        └─ validate_in ──► Agent-3 ──► validate_out ──► analysis-report
              (batch + knowledge)
```

任一 `validate_*` 失败 → **硬停**该步（或标 fail 产物），不得带病进入下一 Agent。

---

## 跨段：契约与固定脚本校验（已确认）

| Artifact | 生产者 | 消费者 |
|---|---|---|
| `raw-defects` | Agent-1 Ingest（内部） | Agent-1 蒸馏及以后 |
| `defect-batch` | Agent-1 | Agent-2、Agent-3 |
| `code-knowledge` | Agent-2 | Agent-3 |
| `analysis-report` | Agent-3 | 人 / 下游业务 Agent |

校验规则：

1. **输入前**：固定脚本（建议 zod / JSON Schema CLI）校验本步所需 artifact；失败不启动该 Agent。  
2. **输出后**：同一套 schema 校验产出；失败不写入「已通过」路径、不触发下游。  
3. Schema **版本化**（如 `schemaVersion`）；三份契约可单开专文，实现前冻结。  
4. 校验是**确定性代码**，不放进模型自由发挥。

---

## 总览

```text
┌─ Agent-1 批次准备（独立单元）─────────────────────────┐
│ Ingest → raw-defects → 蒸馏/筛选/分簇 → defect-batch   │
└──────────────────────────┬────────────────────────────┘
                           │ 仅 artifact + 校验
┌─ Agent-2 代码通读（独立单元）─────────────────────────┐
│ defect-batch → … → code-knowledge                      │
└──────────────────────────┬────────────────────────────┘
                           │ 仅 artifact + 校验
┌─ Agent-3 分析 + 按条 patch（独立单元）─────────────────┐
│ batch + knowledge → 每票完整报告（单信息/根因/方案或   │
│   分类阻断：需测试环境 / 需补单信息…）+ 可选 patch     │
└───────────────────────────────────────────────────────┘
```

原则：

1. **一事一 Agent**：不共享会话上下文（防爆炸）；只传落盘 artifact。  
2. 成本重心在 Agent-3；Agent-1 以规则为主。  
3. 全自动无审批断点。  
4. **松耦合工作流**；契约 + 进出固定脚本校验。  
5. **三段均可注入业务特性 Skill**（见下节）。  

> 曾考虑跨 Agent 共享上下文；已否决。共享 transcript 会随通读+分析膨胀，且破坏「只做一件事」的边界。下游需要的信息应写进契约字段（如 `defectCodeMatches`），而不是把 Agent-2 对话塞进 Agent-3。

---

## 跨段：业务特性 Skill 注入（已确认）

| 项 | 约定 |
|---|---|
| 谁可注 | **Agent-1 / 2 / 3 全部** |
| 注什么 | 业务特性：模块别名、缺陷话术、子应用对照、设备桥约定、分析禁忌等 |
| 来源叠加 | ① Run/`options` ② `{workDir}/.bugfix/skills/` ③ 仓内 `.claude/skills` ④ 本段内置；同名倾向用户/业务覆盖 |
| 分段隔离 | `profiles`：`defect-batch` / `cartography` / `analyze` |
| 挂载 | merge；禁止清空仓内 `.claude/skills` |
| 边界 | 不替代筛池硬规则、不替代 zod 契约、不写缺陷平台 |

---

## 跨段共识摘要

| 项 | 倾向 |
|---|---|
| 产品边界 | 止于分析报告（对齐 10-23）；改码/MR 下游 |
| **集成形态** | **工作流 + 松耦合**；仅 I/O 契约；进出脚本校验 |
| SDD | 封闭已知几种；通读识别 |
| **业务 Skill** | **1/2/3 均可注入** |
| Agent-1 | Skill + 管线 |
| Agent-2 | LangGraph 子图 + Claude Agent SDK（段内）；对外仍只暴露契约 |
| Agent-2 CodeGraph | 用户仓内；跟 `CLAUDE.md` |
| Agent-2 匹配 | 按条；无数量硬限；池=`strict`+`locatable_only`+`needs_info` |
| Agent-2 workDir | 根下可多子仓；不强制单一 git |
| Agent-3 粒度 | **按条修复**；并发用 worktree；各自抽切片 |
| 跨 Agent JSON | **终版不急**（Q-D 随实现） |
| Agent-3 | 每票完整报告；结局分类（方案/patch / 需测试环境 / 需补单信息…）；D1/D2/D3/D5 已拍 |
| 可修文案 | 底层 `outcome` 区分；禁止只贴标签无正文 |

---

## 跨段待拍板

| ID | 问题 | 归属 |
|---|---|---|
| Q-B | 可修/不可修 vs confidence+suggestedAction | Agent-3 |
| Q-D | 三份 artifact **schema 终版** + `schemaVersion` | 契约专文（**不急**；随实现） |
| Q-F | 先正式规格再实现 | 当前：继续探讨 |

~~Q-E 同进程 vs 分服务~~ → **已收敛**：同仓可放，但**逻辑松耦合**；工作流只编排 + 校验，不合并 Agent。

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 合稿初版 |
| 2026-11-01 | 拆成三份专文；Agent-1 收口；Agent-2 补形态/CodeGraph/SDK |
| 2026-11-01 | 三端业务 Skill 注入 |
| 2026-11-01 | **工作流松耦合 + I/O 契约 + 进出固定脚本校验** |
| 2026-11-01 | 明确一事一 Agent、不共享会话上下文；Agent-2 通用 skill 选型见专文 §7.1 |
| 2026-11-01 | Agent-2 §7.1 通用 skill 清单确认按此落地 |
| 2026-11-01 | Agent-2 A/C 收口要点入索引；Agent-3 按条修复；Q-D 不急 |
| 2026-11-01 | Agent-3 专题深化（流程/验证分工/D 组清单） |
| 2026-11-01 23:24 Asia/Shanghai | 时间戳标注；PR 同步提交本批探讨备忘 |
| 2026-11-02 08:38 Asia/Shanghai | Agent-3 D1/D3/D5：分析+patch；取消 GREEN 门禁；不强制验证环境 |
| 2026-11-02 08:42 Asia/Shanghai | Agent-3 D2：每票完整报告与结局分类 |
