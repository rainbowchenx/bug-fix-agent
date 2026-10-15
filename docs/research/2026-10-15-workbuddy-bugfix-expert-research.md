# WorkBuddy「Bug 修复」专家机制调研报告

> 日期：2026-10-15  
> 目的：拆解腾讯 WorkBuddy / CodeBuddy 体系中与缺陷修复相关的专家、子代理与协作路径，评估哪些机制可迁移到本仓本地 BugFix Agent  
> 对应设计：[`docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md`](../superpowers/specs/2026-10-14-local-bugfix-agent-design.md)  
> 上游调研：[`2026-10-14-sota-bugfix-agent-survey.md`](./2026-10-14-sota-bugfix-agent-survey.md)、[`2026-10-14-sentry-seer-autofix-deep-dive.md`](./2026-10-14-sentry-seer-autofix-deep-dive.md)

---

## 0. 执行摘要

1. **没有单独一张「Bug 修复专家」名片**。WorkBuddy 专家中心（COS `expert_center.json`，本稿采样约 **429** 条）里，缺陷修复能力分散在：内置 `debugger` 子代理、「软件开发团队」的 **BugFix 快捷路径**、「软件工坊」的 `gstack-investigator`、以及方法论型专家（如 SuperpowersZh 的系统化调试）。
2. **专家 = Agent 配置包，不是新引擎**。包装物是 `plugin.json` + `agents/*.md`（人设 / SOP / 工具链绑定）+ 可选 Skill；运行时仍是 CodeBuddy 自研 Agent Loop（官方称非 OpenClaw 套壳）。
3. **真正有设计含量的是三条路径**，而不是花名与头像：
   - **路由分流**：Bug → 轻路径，避免套完整研发 SOP；
   - **角色隔离 + 主理人中转**：工程师改码、QA 验证、禁止一人演多角；
   - **假设驱动调试 + 硬上限**：IRON LAW / 3-strike / QA 最多 2 轮。
4. **对本产品的总判断**：产品形态不要学 WorkBuddy 专家市场；**方法论与编排纪律值得吸收**。本仓已具备更强的日批 harness（阶段机、`fixability` 门禁、GREEN→MR）。优先迁移：Bug 专用轻路径措辞、假设→再改、scope lock、验证回环上限与「源码 bug vs 测例 bug」分流。

---

## 1. 调研范围与方法

### 1.1 覆盖对象

| 层级 | 对象 | 与 Bug 修复的关系 |
|------|------|-------------------|
| 运行时 / 产品 | WorkBuddy 桌面工作台、CodeBuddy Agent 底座 | 专家召唤、Skill、MCP、TeamCreate |
| 内置子代理 | `debugger`、`code-reviewer`、`Explore` 等 | 官方文档公开的调试/审查角色 |
| 专家市场 Team | `SoftwareCompany`、`SoftwareWorkshop`(gstack)、`EngineeringAssuranceTeam` | 含 BugFix / 调试 / 事故响应工作流 |
| 专家市场 Agent | `CodeReviewExpert`、`SreExpert`、`SuperpowersZh`、测试类专家等 | 周边能力，非日批修 bug 主路径 |
| 社区对照 | CodeBuddy 生态 `fix-bug` Skill（项目级） | 交互式流水线，含 AskUser / worktree |

### 1.2 方法与材料来源

| 来源 | 用途 | 局限 |
|------|------|------|
| 腾讯云 / workbuddy.cn 官方文档（专家中心、子代理、企业智能体 Manifest） | 产品定义与公开 debugger 全文 | 不暴露全部市场包源码 |
| COS 公开清单 `expert_marketplace/expert_center.json` | 专家 ID、类型、描述、prompt 路径 | 无登录态排行榜；成员 MD 需另拉 |
| COS `/plugins/.../agents/*.md` 原文 | 软件团队 / 工坊调查员等提示词全文 | 版本随市场更新；本稿抓取于 2026-10-15 |
| 社区逆向镜像（如 `vbarter/workbuddy-experts`） | 交叉核对路径与索引 | 快照可能滞后于 COS |
| 本仓设计与 `skills/systematic-debugging` | 迁移对照 | — |

**未获取到的内容（诚实边界）**：

- 客户端安装目录内全部内置专家包的私有变体；
- `software-engineer` / `software-qa` 在 BugFix 路径下是否还有未公开的附加 system reminder；
- 专家团运行时的 TeamCreate / SendMessage 二进制实现细节（仅见 prompt 契约）。

### 1.3 关键澄清：用户感知 vs 实现

用户界面说「召唤专家」，实现上是：

```text
选专家包
  → 加载 agents/*.md 作为 Role Override（覆盖默认助手人设）
  → 挂载声明的 skills / MCP
  → 进入同一套 Agent Loop（推理 → 工具调用 → 回填）
  → Team 型再走 TeamCreate → spawn 成员 → SendMessage 回传
```

因此「专家」是 **可分发的 Agent 模板 + 产品壳**，不是独立微调模型。

---

## 2. WorkBuddy Agent / 专家体系速览

### 2.1 三层能力模型（官方口径）

| 概念 | 产品话术 | 工程本质 |
|------|----------|----------|
| Skill | 让 AI「能做某件事」 | `SKILL.md` 工具/流程包，按需加载 |
| 专家（Agent 型） | 懂某领域的 AI 角色 | 单 Agent：人设 + 方法论 + 工具链 |
| 专家团（Team 型） | 多角色协作交付 | 主理人 orchestrator + 多成员 + SOP |

官方对比句：**Skill = 能力；专家 = 能力 + 经验；专家团 = 多位专家 + 协作流程。**

### 2.2 专家包物理形态

典型目录：

```text
<plugin>/
├── .workbuddy-plugin/plugin.json   # 或 .codebuddy-plugin/
├── agents/<agentName>.md           # YAML frontmatter + 系统提示正文
├── avatars/
└── skills/                         # 可选
```

`plugin.json` 关键字段：`expertType`（`agent`|`team`）、`agentName`、`teamInfo`（团长/成员）、展示用 i18n（`displayName` / `profession` / `tags` / `quickPrompts`）、`skills` 路径数组。

Agent MD 约束（开发规范）：

- frontmatter **禁止**自声明 `tools`（工具权由系统统一分配）；
- Team 主理人须写清 SOP、TeamCreate、成员 Agent ID、禁止代写；
- 成员须约定 **SendMessage 回传主理人**，禁止成员互连。

### 2.3 运行时底座（与 OpenClaw 的关系）

公开访谈口径：WorkBuddy 基于 **CodeBuddy 同一套自研 Agent 架构**，对齐 Claude Cowork 类「能干活」产品形态；**兼容 OpenClaw 技能包格式**，但官方否认使用 OpenClaw 源码。

对本调研的含义：应研究其 **prompt / SOP / 门禁纪律**，而不是假设可直接 fork 其运行时。

### 2.4 企业智能体 Manifest（旁证「专家可嵌套」）

企业版 Agent Manifest 可声明 `system_prompt`、`skills`、`mcp`、`subagents`、`workspaces` 等。说明在腾讯体系里，**专家既可被终端用户召唤，也可被更高层 Agent 当作能力模块挂载**——与本仓「外层编排 + SDK 会话」同构思路。

---

## 3. Bug 修复相关能力地图

### 3.1 总览

```text
                    ┌─────────────────────────────┐
                    │   WorkBuddy / CodeBuddy     │
                    └──────────────┬──────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   内置子代理 debugger      专家市场 Team 路径         周边 Agent / Skill
   (单会话修一个错)         (路由 + 多角色)            (审查 / SRE / 方法论)
           │                       │                       │
           │              ┌────────┴────────┐              │
           │              ▼                 ▼              │
           │     SoftwareCompany      SoftwareWorkshop     │
           │     BugFix 快捷路径      gstack-investigator  │
           │     工程师 → QA          四阶段系统调试       │
           └───────────────────────┬───────────────────────┘
                                   ▼
                    共同模式：根因优先、最小改动、有限回环
```

### 3.2 内置 `debugger` 子代理（官方全文级）

来源：CodeBuddy / WorkBuddy Enterprise「子代理」文档。

```yaml
name: debugger
description: 错误、测试失败和意外行为的调试专家。遇到任何问题时主动使用。
tools: Read, Edit, Bash, Grep, Glob
```

Prompt 要求被调用时：

1. 捕获错误消息与堆栈  
2. 确定复现步骤  
3. 隔离故障位置  
4. 实现**最小修复**  
5. 验证解决方案有效  

过程强调：分析日志、检查近期变更、形成并测试假设、策略性打日志、检查变量状态。  
输出：根因解释、证据、具体代码修复、测试方法、预防建议。

**设计评价**：极短、可复用；适合 IDE 内「请 debugger 调查这个错误」。**没有**独立验证编排器、没有 GREEN 门禁、没有 MR 交付——与日批产品缺口明显。

### 3.3 「软件开发团队」`SoftwareCompany`（含正式 BugFix 路径）

| 项 | 内容 |
|----|------|
| 专家 ID | `SoftwareCompany` |
| 类型 | `team` |
| 主理人 | `software-team-lead`（齐活林 · 交付总监） |
| 成员 | PM / Architect / Engineer / QA（Agent ID：`software-product-manager` 等） |

#### 3.3.1 工作流路由（收到请求先判断）

| 场景 | 判定 | 路径 |
|------|------|------|
| 小型需求 | ≤10 源文件、小工具/单页 | 快速模式：工程师 → QA |
| **Bug 修复** | **明确 Bug，非新功能** | **BugFix 快捷路径：工程师 → QA** |
| 中大型 | 多模块 / 前后端 | 标准 SOP：PM → 架构 → 工程师 → QA |
| 仅分析 | 只要 PRD/架构评审 | 部分工作流 |

原则写得很产品化：**宁选快速模式，不选过重流程**。

#### 3.3.2 BugFix 快捷路径（原文结构）

```text
用户 Bug 报告
  → TeamCreate(software-bugfix-<简称>)
  → 工程师：定位 + 修复（带描述 / 复现 / 期望行为）
  → QA：仅回归确认
```

相对标准 SOP：**跳过 PRD 与架构**，避免用「做产品」的流程修缺陷。这是对本仓最有直接参考价值的产品决策。

#### 3.3.3 工程师角色（`software-engineer`）中与修 bug 相关的约束

- 增量改动：先读现有代码；**Minimal changes**；不整文件重写；保留既有行为；列出改了什么与为何。  
- 被 QA 打回时：默认修源码而非测例（除非测例明显错误）。  
- 团队契约：任务来自主理人 SendMessage；产出完整回传；不擅自编排他人。

（工程师 prompt 主体大量篇幅面向「从零实现」的 ALL-AT-ONCE 写码加速，BugFix 路径主要复用「增量开发」小节。）

#### 3.3.4 QA 角色（`software-qa-engineer`）的验证闭环

**Smart Routing（测完必须做路由决策）**：

| 决策 | 含义 |
|------|------|
| Send To: Engineer | 断言正确、实现错误 → 回传失败测例、期望/实际、文件与堆栈 |
| Send To: QA (self) | 测例断言错误 → 自己改测 |
| Send To: NoOne | 全过 → 成功报告 |

**硬上限：最多 2 轮**（`Write/Fix Tests → Run → Analyze → Route`）。  
第 2 轮仍失败 → **立即退出**，把剩余问题记为 Known Issues，禁止进入第 3 轮。  
理由原文：**延长测试环是交付变慢的头号原因**；2 轮覆盖多数问题，边角记文档而非无限调试。

这对日批系统极关键：与本仓 `maxIterate` / 失败进 `unfixed` 是同一类「预算思维」。

#### 3.3.5 协作铁律（Team 通用）

1. 仅主理人 TeamCreate  
2. 按阶段 spawn，成员独立产出  
3. 跨成员信息必须经主理人中转  
4. 专业结论以成员产出为准，主理人只编排汇编  
5. 禁止主理人模拟多角色、禁止代写、禁止成员互连  

**设计评价**：用 prompt 纪律换「角色隔离」；有效性依赖模型服从与运行时是否真 spawn。对本仓：若拆 analyze / implement / verify 子会话，可借鉴「禁止一人演多角」的验收标准。

### 3.4 「软件工坊」`SoftwareWorkshop` / `gstack-investigator`

主理人 `gstack-lead` 将「排查线上问题，定位根因并修复验证」路由到 **`gstack-investigator`（调查员）**。

调查员系统调试（IRON LAW）：

> No fixes without root cause. Every change must be traced to a proven hypothesis.

四阶段（不可跳过）：

1. **Investigate** — 日志、状态、复现；记录发现  
2. **Analyze** — 映射失败模式目录：  
   - Race condition  
   - Nil propagation  
   - State corruption  
   - Integration failure  
   - Configuration drift  
   - Stale cache  
3. **Hypothesize** — 改代码前显式陈述假设  
4. **Implement** — 假设确认后再改；**Scope lock** 只动根因相关文件  

附加：

- **3-strike**：同一假设失败 3 次 → 停手重查 / 升级，禁止症状补丁  
- Checkpoint / Learn / Retro / Health：偏运维与知识沉淀，日批可只借 Learn 思路（把根因模式写入报告）

**设计评价**：比 SoftwareCompany 的 BugFix 路径更「诊断学」；与本仓已有 `skills/systematic-debugging`（reproduce → isolate → hypothesize → minimal fix）高度同构，说明行业共识收敛。

### 3.5 「工程保障团队」与周边专家（弱相关）

`EngineeringAssuranceTeam` 侧重审查、架构、事故响应、测试策略、文档——**事故响应**接近线上排障，但不是「改仓库开 MR」主路径。  
`CodeReviewExpert`、各类 Testing 专家、`SreExpert`（绑定 CloudQ Skill）属于质量/运维增强，可按需作为本仓可选 Reviewer / 信号源，不宜当作修复主编排。

### 3.6 社区 `fix-bug` Skill（对照，非官方专家卡）

公开仓库中的 CodeBuddy 风格 `fix-bug` Skill 呈现更长流水线：分析 → AskUser 确认方案 → worktree → 改码 → 补测 → fmt/lint/build/test/coverage → 合入确认。  

与本产品冲突点：

- 多处 **AskUserQuestion**（本仓 G13：无中间等人断点）；  
- 默认合入 main（本仓：开 MR、不自动 merge）；  
- 强绑定单仓规范（如 Go / make）。  

价值：展示「Skill 承载端到端修 bug SOP」的另一种包装；本仓已用多个细粒度 Skill + 外层 Orchestrator，方向更可测。

---

## 4. 机制拆解：他们到底在优化什么

| 机制 | WorkBuddy 做法 | 解决的问题 | 风险 / 弱点 |
|------|----------------|------------|-------------|
| 任务路由 | Bug / 小需求 / 大需求分流 | 避免过重 SOP | 误判「小需求」漏设计 |
| 轻量 Bug 路径 | 仅工程师 + QA | 降低延迟与积分 | 缺独立定位阶段产物 |
| 角色隔离 | TeamCreate + SendMessage | 降低自我确认偏差 | 模型可能仍「假协作」 |
| Smart Routing | 区分源码 bug vs 测例 bug | 避免乱改测试「刷绿」 | 依赖 QA 判断质量 |
| 回环上限 | QA 2 轮；investigator 3-strike | 控成本、避免死循环 | 难例过早放弃 |
| IRON LAW | 无根因不改码 | 减少症状补丁 | 交互式成本高 |
| Scope lock | 只改涉事文件 | 控 diff、减回归 | 需正确根因 |
| 产品壳 | 专家卡 / 花名 / 积分 | 可发现、可计费 | 对执行器产品无增益 |
| 验证真值 | 多数仍由 Agent 自称跑测 | 实现简单 | **弱于**本仓 Orchestrator 跑测 |

与 SOTA 调研结论对照：WorkBuddy 强在 **交互式方法论文本化**；弱在 **确定性 harness 与交付门禁**——而这正是本仓相对 Seer 全自动日批的差异化。

---

## 5. 与本仓 BugFix Agent 对照

### 5.1 架构对照

| 维度 | WorkBuddy Bug 路径 | 本仓 `bugfix-agent` |
|------|--------------------|----------------------|
| 触发 | 用户召唤专家 / 自然语言 | Dify 日批 `POST /v1/runs` |
| 编排 | Prompt SOP + Team 工具 | **确定性阶段机**（normalize→aggregate→analyze→implement→verify→deliver） |
| 改码引擎 | CodeBuddy Agent | `@anthropic-ai/claude-agent-sdk` |
| 分析 / 实现 | 常在同一工程师角色 | `mode: analyze \| implement` + 工具白名单已分 |
| 验证 | QA Agent 跑测（软） | **Orchestrator 执行验证命令（硬）** |
| 成功定义 | 对话交付 / deliverables md | **GREEN → push + GitLab MR** |
| 失败定义 | Known Issues / 停止 | **`unfixed` + reasonCode/Detail** |
| 人机断点 | 常见（确认方案、合入） | **明确禁止**（G13） |
| Skill | 市场 / 专家绑定 | 内置 `systematic-debugging`、`minimal-diff`、`verify-green-gate` 等 |
| 多缺陷 | 单会话单问题为主 | **整表聚合分簇，一簇一 MR** |

### 5.2 能力重叠与缺口

**本仓已覆盖或更强**：

- 全自动双结局报告；  
- Stack Profile 探测与验证命令；  
- fixability 门禁与无 GREEN 不开 MR；  
- 簇级产物目录（root-cause / solution / verify）；  
- 不把 git push / 建 MR 交给模型自由发挥。

**WorkBuddy 更明确写进 prompt、本仓可加强的**：

- 「这是 Bug → 走轻路径」的显式路由话术（避免分析阶段写成大型重构方案）；  
- 失败模式目录（竞态 / 空值传播 / …）作为 analyze 结构化枚举；  
- QA Smart Routing：验证失败时区分「实现错误 vs 测例/命令错误」再 iterate；  
- 3-strike / 轮次上限与 Known Issues 文案对齐 `unfixed.reasonDetail`；  
- Scope lock 与 `minimal-diff` Skill 互相强化。

**明确不迁移**：

- 专家市场 UI、花名、积分、默认 AskUser；  
- 以 Team 花活替代阶段机；  
- 依赖模型「自称测试通过」。

---

## 6. 可迁移建议（按优先级）

### P0 — 低成本、对齐现有流水线

1. **强化 analyze prompt / `systematic-debugging` Skill**  
   - 写入 IRON LAW 一句版：无证据假设不进入 implement。  
   - 增加失败模式枚举（可与 root-cause.json 字段对齐）。  
2. **Implement 明确 Scope lock**  
   - 只允许 solution 计划内的文件；偏离记入日志或直接 unfixed。  
3. **Iterate 预算语义对齐 QA 2 轮**  
   - 耗尽后写入 Known Issues 风格的 `reasonDetail`（已做动作、剩余风险）。

### P1 — 编排增强（仍保持全自动）

4. **验证失败分类器（Smart Routing 确定性版）**  
   - Orchestrator 根据测试输出启发式：疑似 flaky / 环境 / 断言 / 产品代码；  
   - 仅「产品代码」类进入下一轮 SDK implement；环境类直接 `unfixed`。  
5. **可选独立 Reviewer 子会话**（对标 code-reviewer / 工程保障）  
   - 只读 + 反对称检查；不通过则不再开 MR（与 SOTA 调研 P1 一致）。

### P2 — 产品化包装（仅当需要对外「专家」叙事时）

6. 将现有流水线导出为「BugFix Agent 定义包」（MD + skills 清单），供内部复用——**不必**做成 WorkBuddy 市场卡。  
7. 若未来要做多角色：固定 `localizer` / `fixer` / `verifier` 三个子 Agent 定义，主理人逻辑留在 TypeScript 阶段机，而不是纯 prompt TeamCreate。

### 不建议做的

- 为了「像 WorkBuddy」引入专家中心与积分；  
- 用自由 multi-agent 聊天替换 GREEN 门禁；  
- 把 AskUser 确认方案加回日批主路径。

---

## 7. 建议的内部对照实验（可选）

若要量化「WorkBuddy 方法论注入」是否涨点，建议在现有评测集上做 A/B（不必接 WorkBuddy 客户端）：

| 组 | 变更 | 看什么 |
|----|------|--------|
| A 基线 | 当前 analyze/implement/skills | GREEN 率、MR 率、人均改动行数 |
| B | + IRON LAW / 失败模式 / scope lock 文案 | 同上 + unfixed 原因分布 |
| C | + 验证失败 Smart Routing | 无效 iterate 次数、费用 |

成功标准：B/C 在不明显增加耗时的前提下，提升「一次合入率」或降低「症状补丁型 diff」。

---

## 8. 结论

WorkBuddy 的「Bug 修复专家」**不是**一个神秘垂直模型，而是：

1. 短小的 **`debugger` 子代理**；  
2. 软件团队里的 **BugFix 快捷 SOP**（工程师 → QA + 2 轮上限）；  
3. 工坊调查员的 **假设驱动调试协议**（IRON LAW / 3-strike / scope lock）；  
4. 统一的 **专家包分发壳**（plugin + MD + Skill）。

对本仓：继续以 **Seer 式全自动双结局 + SWE harness 门禁** 为主航道；把 WorkBuddy 当作 **prompt / SOP 方法论库** 吸收 P0/P1，而不是换产品形态。

一句话：**学它的修 bug 纪律，不学它的专家货架。**

---

## 9. 参考链接与材料

### 官方

- 专家中心：https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Expert-Center  
- WorkBuddy Enterprise 专家：https://cloud.tencent.com/document/product/1831/134393  
- 子代理（含 debugger 全文）：https://www.workbuddy.ai/docs/zh/cli/sub-agents  
- 企业智能体 / Manifest：https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/CloudAgent  
- 插件参考：https://www.workbuddy.ai/docs/cli/plugins-reference  

### 公开市场数据（采样时）

- Manifest：`https://acc-1258344699.cos.accelerate.myqcloud.com/workbuddy/expert-marketplace/expert_center.json`  
- 相关 prompt 路径示例：  
  - `/plugins/software-company/agents/software-team-lead.md`  
  - `/plugins/software-company/agents/software-engineer.md`  
  - `/plugins/software-company/agents/software-qa-engineer.md`  
  - `/plugins/gstack/agents/gstack-investigator.md`  

### 本仓

- 设计规格：`docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md`  
- SOTA harness 调研：`docs/research/2026-10-14-sota-bugfix-agent-survey.md`  
- Seer 深潜：`docs/research/2026-10-14-sentry-seer-autofix-deep-dive.md`  
- 内置 Skill：`skills/systematic-debugging/SKILL.md`、`skills/minimal-diff/SKILL.md`、`skills/verify-green-gate/SKILL.md`
