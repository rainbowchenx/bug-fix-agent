# Agent-3 探讨：缺陷分析与按条修复

> 日期：2026-10-30  
> **最近修订：2026-11-02 08:42（Asia/Shanghai）**  
> 状态：**探讨中**（非正式规格；D1/D2/D3/D5 已拍，其余 D 待确认）  
> 索引：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)  
> 上游：[Agent-1](2026-10-30-agent1-defect-batch-discussion.md) · [Agent-2](2026-10-30-agent2-code-cartographer-discussion.md)  
> 对照：[报告型分析 Agent 设计](2026-10-23-report-agent-design.md)（10-23）· [本地 BugFix 设计](2026-10-14-local-bugfix-agent-design.md)（10-14）  
> **实现与细则请优先回看仓内既有分析/对比文档**（§1.1），勿从零发明阶段语义与编号。

---

## 0. 结论（当前倾向）

| 项 | 倾向 |
|---|---|
| 职责（**D1**） | **按条主做分析**：定位 → **根因** → **修复方案** →（可行动则）产出 **代码 patch** |
| 报告（**D2**） | **每票完整报告**（单信息+根因+方案或分类不可修原因）；`needs_test_env` / `needs_ticket_info`（含补什么）等须区分 |
| 输入 | `defect-batch`（含蒸馏正文）+ `code-knowledge`；只传 artifact；按条切片 |
| 粒度 | 一条一会话；并发可用 worktree |
| 相对 10-23 | 仍以分析报告为核心；**额外产出 patch**（非 BOUND-1 纯报告）；保留路由/举证纪律 |
| 相对 10-14 | 对齐全自动、双结局；**不沿用「没有 GREEN 就没有成功交付」**（见 D3/D5） |
| 验证（**D5**） | **不强制本地验证环境**（业务环境复杂、常无法本机拉起）；验证为可选增强，缺省可完全跳过 |
| 运行时 | LangGraph + Claude Agent SDK（待 D8 确认） |
| 业务 Skill | 可注入（`analyze` / `fix`；`verify` 可选） |
| 设计依据 | 复用仓内分析/对比文档（§1.1） |

---

## 1. 与既有文档的关系

### 1.1 仓内分析 / 对比文档（Agent-3 必读参考）

Agent-3 的定位、根因、路由、验证、交付与报告字段，**优先对照下列已有材料**（含编号体系），再在本专文做「三 Agent + 按条修复」差分。拍 D 组 / 写实现时按表回查，避免与历史结论打架却不自知。

| 文档 | 对 Agent-3 的用途 |
|---|---|
| [目标流水线设计](2026-10-22-target-pipeline-design.md) | **主流程骨架**：`S0..S6` 定位/根因/方案 + **产出 patch**；`LOC-*` 等编号复用。`S7` 验证执行 **非默认门禁**（D5）；`S8–S9` MR 交付见 D6/D7（待拍） |
| [报告型分析 Agent 设计](2026-10-23-report-agent-design.md) | 报告契约、`confidence` / `suggestedAction`、`ruledOut` / `openQuestions`、`CONF-*` 降级；**BOUND-1 只分析**对本工作流放宽（见 D1） |
| [报告型分析 Agent 决策备忘](2026-10-23-report-agent-decision-memo.md) | 落地前 `Q-*` / `U-*` / `J-*` / `R-*`；Agent-3 拍板时对照，避免重复争议 |
| [缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md) | 输入现实：`OBS-*` / `INV-*` / 无堆栈文本缺陷等；分析时不可假设「必有 stack」 |
| [环境适配层与能力降级](2026-10-22-environment-adapter-and-capability-degradation.md) | `EnvironmentProfile`、`capabilities`、`L0..L3` 降级；验证不可用时如何降级（对接 D5） |
| [实现缺口分析与路线图](2026-10-17-implementation-gap-analysis-and-roadmap.md) | 现状 vs 设计 vs 效果：`GAP-*`；哪些分析/修复能力已有代码可迁入 Agent-3 |
| [本地 BugFix 设计](2026-10-14-local-bugfix-agent-design.md) | 双结局、GREEN、全自动无断点；与按条 worktree 的产品对齐 |
| [Phase A 可信闭环](../plans/2026-10-17-phase-a-trusted-loop.md) | **worktree 隔离**、skills 挂载、零改动不开 MR 等已落地决策 |
| [Phase B 修复真值](../plans/2026-10-18-phase-b-fix-truth.md) | baseline / `verifyLevel` / localization 注入等修复真值字段——报告与门禁可对照 |
| [SOTA BugFix 调研](../../research/2026-10-14-sota-bugfix-agent-survey.md) | harness × 模型、验证与交付门禁的外部对照 |
| [Sentry Seer 深潜](../../research/2026-10-14-sentry-seer-autofix-deep-dive.md) | 步进/可修性/hand-off；**刻意分歧**：我们无 stopping_point 等人 |
| [WorkBuddy 调研](../../research/2026-10-15-workbuddy-bugfix-expert-research.md) | 多专家/子代理拆分；可映射「分析 vs 改码」会话，但本产品仍一事一 Agent-3 单元 |
| [LangGraph 引擎说明](../../langgraph.md) | 现有 `pipeline` vs `langgraph` 双引擎；Agent-3 子图应复用步骤函数而非分叉两套语义 |
| [Agent Harness 设计笔记](../../agent-harness-design-notes.md) | 会话/prompt 差分等 harness 机制，编排层可借鉴 |

> **用法约定**：讨论或实现 Agent-3 某能力时，先搜上表编号（如 `LOC-L3`、`GATE-*`、`CONF-*`、`GAP-*`），再决定是「直接采纳」还是「三 Agent 差分覆盖」。差分必须在本专文或后续契约文写明，禁止静默改义。

### 1.2 与 10-23 / 10-14 的关系（产品边界差分）

| 来源 | 采纳 | 废弃 / 放宽 |
|---|---|---|
| 10-23 | 分析为核心；路由/举证/双形态报告 | BOUND-1 放宽为 **可出 patch**（D1）；不是「以开 MR 为成功」 |
| 10-14 | 全自动、双结局、按隔离区改码 | **废弃对本段的 GREEN 硬门禁**（D3/D5）：本地测绿不是成功前提 |

对外仍可说「可修 / 不可修」**文案**，底层建议映射到 `suggestedAction` + 结局桶，避免重新发明 fixability gate。

---

## 2. 端到端流程（按条）

```text
【输入】已校验 defect-batch + code-knowledge
        │
        ▼
┌─ batch_orchestrator（LangGraph）──────────────────────────┐
│  展开待处理票（池对齐 Agent-2 C1：strict+locatable+needs_info 等）│
│  串行 或 有限并发（每票独立 worktree）                         │
└──────────────────────────┬────────────────────────────────┘
                           ▼  per defectId
┌─ ticket_subgraph ─────────────────────────────────────────┐
│  1. slice      抽该条 digest + matches + modules/DR         │
│  2. localize   定位（matches 软起点）                        │
│  3. rootCause  根因；ruledOut / openQuestions               │
│  4. propose    修复方案（不要求当场可跑验证）                 │
│  5. route      confidence + suggestedAction                 │
│     ├─ 非 code_fix → unfixed（原因码）+ 分析正文         │
│     └─ code_fix →                                        │
│  6. patch      产出代码 patch（worktree / diff 产物）        │
│  7. verify?    **可选**（默认跳过；环境复杂常无法本机启动）   │
│  8. deliver?   MR 等交付见 D6/D7（待拍；非主路径必选项）     │
│                → patched / unfixed                          │
└──────────────────────────┬────────────────────────────────┘
                           ▼
【输出】analysis-report：分析 + 方案 +（有则）patch 路径/diff
         桶名倾向 patched[] / unfixed[]（或 fixed=已出 patch，见 §4）
```


原则：

1. **一事一会话**：每票独立 SDK 上下文；不把其它票的 diff/对话带进来。  
2. **切片而非灌仓**：只注入该条需要的 batch 字段 + knowledge 相关片段。  
3. **全自动**：route / 失败后不等人；写清原因进报告。  
4. **松耦合**：不回调 Agent-1/2 内部；缺知识就在本段降级检索并记 `partial`/`openQuestions`。

---

## 3. 运行时形状

与 Agent-2 同构，但节点不同：

| 层 | 职责 |
|---|---|
| 父工作流 | validate(batch, knowledge) → 调 Agent-3 单元 → validate(report) |
| Agent-3 LangGraph | `batch_orchestrator`：调度票、worktree 生命周期、汇总 |
| `ticket_subgraph` | slice → localize → rootCause → propose → route → patch →（可选）verify/deliver → emit |
| Claude Agent SDK | 分析与出 patch 的会话；挂载 analyze/fix skills（verify 可选） |
| 确定性代码 | worktree、落盘 patch/diff、schema 校验、结局归桶；**不依赖**本机起全套业务环境 |

**不宜**学 Agent-1 做成纯 Skill+管线：分析+方案+patch 仍需 SDK 会话。

---

## 4. 单票完整报告与结局分类（D2）

### 4.1 原则（已确认）

**每一条缺陷都必须有一份完整报告**，不能只给「可修/不可修」标签。至少包含：

| 区块 | 内容 |
|---|---|
| **缺陷单信息** | 来自 batch 的原文切片：id、标题、模块/括注/意图（若有）、实际/期望/步骤摘要、附件提示等 |
| **定位** | 代码候选 / 范围（消费 `defectCodeMatches`，可扩展） |
| **根因分析** | 证据链、`ruledOut`、`openQuestions` |
| **结局正文（互斥分区，必须区分开）** | 见 §4.2——要么写清**修复方案**（+ 可选 patch），要么写清**不可修/暂不可行动原因**（分类 + 要补什么） |
| **建议验证** | 文档级「建议怎么验」（不强制本机执行，对齐 D5） |

汇总层仍可按结局码分组浏览，但 **MD/JSON 都以「每票完整条目」为真源**，禁止只有桶名没有正文。

### 4.2 结局类型（须区分，不可混写）

对外可用文案「可修 / 不可修」，底层用 **`outcome` + 专用字段**（对齐 10-23 `suggestedAction` 精神，字段名终版不急）：

| `outcome` | 含义 | 强制正文 |
|---|---|---|
| `patch_ready` | 已给出修复方案，并产出 patch（或不强制 patch 时至少方案可落地） | **修复方案**；`patchPath` / diff 摘要（有则） |
| `plan_only` | 方案已写清，因策略未出 patch（可选细分） | **修复方案**；说明为何未出 diff |
| `needs_test_env` | **必须依赖测试/运行环境**才能继续定因或给出可靠 patch（Agent-3 **本机不起环境**，故停在此） | 不可修原因；**需要什么样的环境/数据/机台**；建议验证步骤 |
| `needs_ticket_info` | **缺陷单信息不足**，需业务/测试补单 | 不可修原因；**`missingInfo[]`：要补充哪些字段/材料**（复现步骤、期望、日志、截图、版本、机型…） |
| `needs_design_input` | 缺设计/产品确认 | 缺什么决策、问谁 |
| `not_code` / `config_or_dependency` | 非代码或配置/依赖侧 | 建议流转路径 |
| `unlocalized` | 无法定位到代码 | 已尝试范围、`openQuestions` |
| `other_blocked` | 其它阻断 | `reasonDetail` |

> **与 D5 的关系**：D5 = Agent-3 **不强制本机起验证环境**。`needs_test_env` 不是「没起环境就失败」，而是报告里的一种**明确分类**：继续推进**强制需要**测试环境/实机信息——与「缺单信息」「已出方案/patch」必须分开写，禁止糊成一句「不可修」。

### 4.3 单票条目草案（字段方向，schema 不急冻）

```jsonc
{
  "defectId": "",
  "ticket": { /* 缺陷单信息切片 */ },
  "localization": { /* … */ },
  "rootCause": { "summary": "", "ruledOut": [], "openQuestions": [] },
  "outcome": "patch_ready | plan_only | needs_test_env | needs_ticket_info | …",
  "proposedFix": null,           // outcome∈{patch_ready,plan_only} 时必填
  "patch": null,                 // 可选 { "path": "", "summary": "" }
  "blockers": null,              // 不可行动时必填
  // blockers 示例：
  // { "kind": "needs_ticket_info", "missingInfo": ["复现步骤", "期望结果截图"], "detail": "" }
  // { "kind": "needs_test_env", "envNeeds": ["实机摄像头固件 x.y", "可登录的测试账号"], "detail": "" }
  "suggestedVerify": { "steps": [], "executed": false },
  "confidence": "high|medium|low"
}
```

### 4.4 关于 D3「GREEN」——说明与决定

**D3 原意**：沿用 10-14 的 **「没有 GREEN，就没有 MR / 不进成功桶」**——这里的 GREEN = **本地验证命令跑通**（测试/构建等变绿），不是「代码语法绿」或「CI 远程绿」的别称 alone。

| 原建议 | 现决定（2026-11-02） |
|---|---|
| 无 GREEN 不进 fixed | **取消该门禁**。成功以「分析完整 +（可行动时）已出 patch」为准；**不以本地测绿为条件** |

报告中若偶尔跑过验证，可记 `verifyStatus=passed|failed|skipped`（默认 **skipped**），**不**用它挡 patched 归桶。

---

## 5. 验证：不强制本机环境（D5）

业务验证环境复杂，**不一定能在本地启动** → Agent-3 **不对验证环境做硬性要求**。

| 能力 | Agent-2 `runtimeVerify` | Agent-3 |
|---|---|---|
| 默认 | off | **`verifyMode=off`（默认）** |
| 可选 | 通读期摸环境 | 若用户注入 skill / 显式打开，才尝试命令或引导验证 |
| 失败 / 不可用 | 不影响主路径 | **不影响** patched 归桶；只记 `verifyStatus` |

验证方案仍应写进分析（「建议怎么验」），与 10-23「设计验证方案、不强制执行」一致；差别是本段**额外可出 patch**。

---

## 6. `defectCodeMatches` 用法

| 策略 | 说明 | 建议 |
|---|---|---|
| 强制起点 | 无候选则不改码 | 过严（C1 旁路票可能无强匹配） |
| 仅参考 | 可完全忽略 matches | 浪费 Agent-2 |
| **软起点（推荐）** | 有候选→优先；空/低置信→本段可降级 Glob/Grep/CodeGraph 再搜；仍无则 `suggestedAction` 倾向 needs_* 或 unfixed | **默认** |

---

## 7. 业务 Skill 注入

`profiles` 建议：`analyze` | `fix`（主）；`verify` 仅当显式打开验证时有用。

典型：业务根因话术、禁忌目录、子应用/IPC/桥、**建议验收步骤（文档级）**。  
不取消：路径存在性等可计算检查、schema 校验。**不**把本机测绿当纪律门禁。

---

## 8. 拍板清单

### 8.1 已确认

- [x] 松耦合；只传 artifact；不共享跨 Agent 会话  
- [x] 业务 Skill 可注入  
- [x] 按条处理；worktree 并发；蒸馏正文本段按条取用  
- [x] 跨 Agent JSON 终版不急  
- [x] **D1（2026-11-02）**：Agent-3 **主做分析**——根因、修复方案、**代码 patch**（不是以本地验绿/开 MR 为中心）  
- [x] **D2（2026-11-02）**：**每票完整报告**（单信息+根因+方案或分类不可修原因）；`needs_test_env` / `needs_ticket_info`（含要补什么）等必须区分（§4）  
- [x] **D3（2026-11-02）**：取消「无 GREEN 不进成功桶」（见 §4.4）  
- [x] **D5（2026-11-02）**：不强制本机验证环境；与 D2 的 `needs_test_env` **原因分类**不矛盾  

### 8.2 D 组——仍待确认

| ID | 问题 | 建议默认（可改） |
|---|---|---|
| **D4** | `defectCodeMatches` | **软起点**（§6） |
| **D6** | 交付形态 | 主交付 = 报告 + patch 产物；**默认不开 MR**（分析+patch 工作流）；开 MR 作可选开关 |
| **D7** | 若开 MR：一票一 MR？ | 开 MR 时默认一票一 MR |
| **D8** | 运行时 | LangGraph + Claude Agent SDK |
| **D9** | 并发 | 默认串行；`maxParallelWorktrees` 可配 |
| **D10** | 迭代预算 | 出 patch 的尝试次数默认 `maxIterate=3` |

### 8.3 E 组——可延后

| ID | 问题 |
|---|---|
| **E1** | report / 单票结果 JSON 终版（Q-D） |
| **E2** | 与 10-23 六段报告字段差分表 |
| **E3** | worktree 在「多子仓 workDir」下的路径约定 |
| **E4** | 安全旁路票是否进入 Agent-3 |
| **E5** | 实机/设备 web 验证的专用 skill 样例 |

---

## 9. 与现有代码

| 现有 | 关系 |
|---|---|
| `pipeline/analyze.ts` / `implement` / `verify` / `deliver` | 逻辑可迁入 Agent-3 单元，但编排改为按条 + worktree；语义对齐 §1.1 流水线编号 |
| `src/graph/*` + `sdk-runner.ts` | 复用挂载；Agent-3 **独立子图**，勿与 Cartographer 状态混用 |
| 10-23 报告渲染 | 可作 MD/JSON 骨架，叠加 fixed/unfixed |
| Phase A/B 已落地行为 | worktree、baseline、verifyLevel 等——Agent-3 默认**继承精神**，差异进 D/E |

---

## 10. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出（较薄） |
| 2026-11-01 | 业务 Skill；松耦合；按条修复 + worktree；相对止于报告放宽 |
| 2026-11-01 | **专题深化**：流程/运行时/双结局/验证分工/matches 软起点；D/E 拍板清单 |
| 2026-11-01 | **§1.1**：明示 Agent-3 须参考仓内既有分析/对比文档（流水线/报告/缺口/调研/Phase A·B 等） |
| 2026-11-01 23:24 Asia/Shanghai | 时间戳标注；随三 Agent 探讨 PR 同步 |
| 2026-11-02 08:38 Asia/Shanghai | **D1/D3/D5**：主责分析+方案+patch；取消 GREEN 门禁；不强制验证环境 |
| 2026-11-02 08:42 Asia/Shanghai | **D2**：每票完整报告；结局分类区分（方案/patch vs 需测试环境 vs 需补单信息等） |
