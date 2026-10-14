# Issue / 缺陷修复 Agent SOTA 与 Harness 调研报告

> 日期：2026-10-14  
> 目的：为本地 BugFix Agent（Dify 编排、Claude Agent SDK 二次包装）站在现有开源/工业实现肩膀上做设计采纳  
> 对应设计：[`docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md`](../superpowers/specs/2026-10-14-local-bugfix-agent-design.md)

---

## 0. 执行摘要

1. **SOTA 分数同时依赖「模型 × harness」**。固定模型换 harness，SWE-bench Verified 可差约 **19pp**；固定 harness 换模型差约 **23pp**（Harness Effects 论文 / Epoch 等综述量级一致）。只卷模型不够，**编排与观测空间是一等公民**。
2. **当前榜单近饱和**：2026 年中后，SWE-bench Verified 在 mini-SWE-agent（bash-only）上，顶尖模型已到 **~96–97%**。产品差异更多在：**真实缺陷信号、本地验证、交付门禁、成本/可控性**，而非再堆一个「更花哨的 agent 环」。
3. **效果好的系统几乎都共享这些 harness 优化**：
   - **分层/分阶段**（定位→方案→改码→验证→选优），而不是一次自由漫游到底
   - **测试/执行反馈闭环**（回归 + 复现；失败 iterate / 多样本 rerank）
   - **结构化工具与任务专用子代理**（比「再多一层通用脚手架」更稳）
   - **编辑观测质量**（edit 后立刻回显、lint 挡坏编辑）
   - **推理时扩展**（多样本 + critic/投票）在难例上显著抬分
4. **对我们项目的总判断**：设计方向（外层编排 + SDK 改码 + GREEN 硬门禁 + 一簇一 MR）与 SOTA 主流一致；应**刻意吸收** Agentless/Seer 的阶段产物、OpenHands 的多样本/选优思想、SWE-agent 的编辑反馈、Aider 的 repo map / architect-editor、Claude 的 adversarial verify；**避免**把 Hermes 式「万能个人助手」复杂度整仓搬进来，也避免无门禁的单次长会话一把梭。

---

## 1. 调研范围与方法

### 1.1 覆盖对象

| 类别 | 代表 |
|------|------|
| Benchmark / SOTA | SWE-bench Verified、mini-SWE-agent 榜、OpenHands scaling |
| 学术/开源修复 harness | SWE-agent、mini-SWE-agent、Agentless、AutoCodeRover、SpecRover、Moatless、Aider |
| 通用编码 harness | OpenHands、Pi (badlogic/pi-mono)、Claude Agent SDK / Dynamic Workflows |
| 垂直缺陷域 | Sentry Seer Autofix、Mangonaut / Samba / sentry-claude-auto-pr |
| 通用 agent（含 coding posture） | NousResearch Hermes Agent |
| 多 agent 编排实验 | pi-company（role isolation + adversarial verify） |
| Harness 实证 | *Beyond the Model: Demystifying Harness Effects…* (2026) |

### 1.2 方法

- 官方文档 / 论文 / 博客 / GitHub README 与关键源码路径
- 关注：**为何有效**、**编排阶段**、**工具与观测**、**验证与选优**、**对我们可迁移点**
- 分数会随时间漂移；本报告强调**可迁移机制**，分数仅作量级参考

### 1.3 重要澄清：分数不可跨 harness 直接比

SWE-bench 官方强调：全榜是「任意系统」对比；**模型公平对比**应看 **mini-SWE-agent bash-only**。产品系统（OpenHands、Claude Code 包装等）分数含 harness 红利。

---

## 2. SOTA 格局（2026-10 量级）

| 信号 | 含义 |
|------|------|
| Claude Opus 系列 + mini-SWE-agent ≈ **97%** Verified | 强模型 + 极简 harness 已极高 |
| DeepSeek / GPT 系列同 harness ≈ **96%+** | 模型能力整体上移 |
| 同模型不同 harness 差距可达 **~20pp** | harness 仍关键，尤其对中弱模型与开放任务 |
| OpenHands：单轨迹 → 多样本 + Critic | **推理时扩展**是抬分主杠杆之一 |
| Agentless（早期 Lite ~32% 开源 SOTA） | 证明「固定流水线 + 验证选优」可低成本打赢复杂 agent |

**对本产品的启示**：不要以「再刷一点 SWE-bench」为北极星；应以 **本地 GREEN 率、MR 可合并率、簇覆盖率、回滚率、人审改动量** 为质量 KPI。

---

## 3. 逐系统深潜

### 3.1 SWE-agent → mini-SWE-agent

**定位**：学术开创的「Agent-Computer Interface (ACI)」；现官方推荐用 **mini-SWE-agent**（更简单，性能相当）。

**为何有效**：

| 机制 | 说明 |
|------|------|
| ACI 而非裸 shell | 专用 viewer/edit；观测简洁、信息密度高 |
| Edit + 即时回显 | 改完自动展示文件窗口，减少「盲改」 |
| Lint guardrail | 引入严重语法错误的 edit 回滚；论文测约 **-3pp** 若去掉 lint |
| Thought + Action | 格式错误重试，稳定轨迹 |
| mini：仅 bash + 线性历史 | 可移植、可沙箱；评测/微调友好 |
| 无状态 `subprocess.run` | 每条命令独立，稳定性与横向扩展更好 |

**编排**：自由 ReAct 环，直到 submit；靠环境与 ACI 约束，而非强阶段机。

**采纳建议**：Implement 阶段沿用 SDK 的 Read/Edit；外层加 **PostToolUse lint/语法检查**；失败观测写回下一轮。不必自研完整 ACI。

---

### 3.2 Agentless（OpenAutoCoder）

**定位**：刻意 **agentless**：LLM 只做分步任务，不自主选工具。

**三阶段**：

1. **Localization**：文件 → 类/函数 → 细粒度 edit 位置（LLM + IR）
2. **Repair**：多样本 Search/Replace patch
3. **Validation**：回归测试筛选 + **生成 reproduction test** → rerank / majority vote

**为何有效**：

- 把「探索自由度」换成「阶段确定性」，降低跑偏与成本
- **多样本 + 测试选优** 比单次生成更稳
- 复现测试缓解「只过无关测试」的假绿

**采纳建议（高优先级）**：

- Scope/RootCause 阶段做 **层次化定位产物**（files → symbols → lines）
- Plan 后 Implement 可 **多样本候选**（N=2~3，成本可控）
- Verify 除仓库测试外，尽量 **生成/记录簇级复现步骤或最小测试**

---

### 3.3 AutoCodeRover / SpecRover

**AutoCodeRover**：

- AST/结构感知的 code search API（按方法/类而非纯字符串）
- 可选 **SBFL**（频谱故障定位）增强检索提示
- Patch 生成 + 测试失败有限次重试

**SpecRover**：

- 检索过程中沉淀 **意图/规格（function summary）**
- **Reviewer agent** 结合规格、生成测试、自然语言需求审查 patch
- 回归失败最多重试（如 3 次）并给出置信证据

**为何有效**：结构检索提高定位；规格+审查降低「看起来对、语义错」。

**采纳建议**：

- Scope 优先 **符号级**（对 TS/Vue 可用 AST/ts-morph 或简单 outline，不必一次上全 SBFL）
- 增加轻量 **Reviewer** 步（可只读）：对照 Plan 验收标准查 diff
- Iterate 上限与 SpecRover 类似的 **3 次** 对齐我们已有 `maxIterate`

---

### 3.4 Moatless Tools

**定位**：状态机式 flow + **好工具优先于让模型空想**；向量检索辅助。

**启示**：工具质量 > 花哨规划；flow 可配置（tools / react / reasoning）。

**采纳**：Stack Profile + 固定 Orchestrator 状态机，与 Moatless「FSM + 好工具」同构。

---

### 3.5 Aider

**关键机制**：

| 机制 | 作用 |
|------|------|
| **Repository map** | AST/调用图压缩全仓结构，按相关度裁剪进上下文 |
| **Architect / Editor 双模型** | 强模型规划，编辑模型产结构化 diff |
| 测试失败重试 | lint/单测失败整轮重来 |

**为何有效**：定位阶段不靠盲目 grep；规划与「写出合法 diff」解耦。

**采纳建议**：

- 每簇 Prepare 前生成 **轻量 repo map**（或 package 级 outline）注入 RootCause/Plan
- 与我们「RootCause/Plan 外置 + SDK Implement」天然同构（architect-editor）

---

### 3.6 OpenHands

**机制**：

- 完整 coding agent + 事件自动化
- **Inference-time scaling**：多轨迹 rollout，分数近似 log-linear 提升
- **训练 Critic** 比纯 prompt rerank 更强（研究向；产品可用 LLM judge 近似）

**采纳建议（中优先级）**：

- 难簇（低置信 / 首次 Verify 失败）启用 **N 轨迹 + 以 Verify 结果选优**（不必上训练 critic）
- 选优准则：**测试通过 > 改动行数少 > 覆盖簇内缺陷更多**

---

### 3.7 Claude Agent SDK / Claude Code Dynamic Workflows

**能力**：内置工具、权限、Hooks、Sessions、MCP、Subagents；Dynamic Workflows 用 JS 脚本编排多 agent（`agent` / `parallel` / `pipeline`），支持 schema 校验、worktree、对抗验证模式。

**官方强调的质量模式**：

- Fan-out + synthesize
- **Adversarial verification**（修的人与审的人隔离）
- Generate-and-filter / loop-until-done
- 编排进**代码**而非全靠主会话记忆

**采纳建议（高优先级）**：

- 外层 Orchestrator = 我们的「静态 dynamic workflow」
- Implement 与 **Reviewer/Tester** 分会话（或分阶段 prompt），避免同一上下文既当运动员又当裁判
- 有预算时：Reviewer 只读 worktree + 对照 Plan

---

### 3.8 Pi Coding Agent（badlogic/pi-mono）

**定位**：极简终端 harness；默认 `read/write/edit/bash`；可扩展 skills/extensions；刻意不做内置 MCP/subagent/plan（留给扩展）。

**相关生态**：

- **harness-pi / pi-bench**：SWE 评测适配；**官方测试为真值**，LLM judge 仅解释
- **pi-company**：多角色（lead/coder/reviewer/tester）+ **契约协商** + 对抗验证；同模型下 resolve 率可显著高于单 agent

**为何有效**：工具少而稳；质量靠**编排角色隔离**而非堆工具。

**采纳建议**：

- 工具集保持克制（SDK 子集即可）
- 中长期可引入 **Tester/Reviewer 角色隔离**（学 pi-company，一期可用顺序阶段近似）

---

### 3.9 Hermes Agent（NousResearch）

**定位**：自改进通用 agent（记忆、skills 闭环、多通道 gateway、多终端后端、subagent、coding posture）。**不是**专注 SWE-bench 的缺陷修复产品。

**与缺陷修复相关的 harness 经验**（从其工程与 issue 可见）：

- 上下文压缩 / compaction 必须与「实际上送模型的 wire payload」一致，否则死循环或假触发
- Coding posture 与项目 `AGENTS.md` 的 commit/push 策略需一致，避免「不敢提交」
- Fallback provider、incomplete 响应恢复等 **可靠性工程** 很重

**采纳建议**：

- **学可靠性**：压缩策略谨慎（Harness Effects 也指出压缩可能伤仓库级任务）；长轨迹优先落盘观测而非激进摘要
- **不学产品形态**：一期不做跨会话记忆库、多 IM gateway；我们明确「无业务存储」

---

### 3.10 Sentry Seer Autofix（垂直领域 SOTA 参考）

> **深潜专报（源码级）**：[`2026-10-14-sentry-seer-autofix-deep-dive.md`](./2026-10-14-sentry-seer-autofix-deep-dive.md) —— 流水线、双轨 fixability、聚合、handoff、PR iteration、与本设计逐条映射。

**流水线**（与工业实践高度对齐）：

```text
root_cause → solution → code_changes → (open_pr | coding_agent_handoff)
            ↘ pr_iteration（CI / 反馈）
```

**关键设计**：

| 点 | 说明 |
|----|------|
| 富缺陷上下文 | 堆栈、trace、logs、profiles + 代码映射解析 in-app frames |
| 分步 artifact | 每步 schema 化产物；可 stopping_point |
| Fixability / automation tuning | 不够可修则不自动开 PR |
| Handoff | 根因+方案打包给 Claude/Cursor/Copilot 做实现 |
| PR iteration | 用 CI 失败继续修 |

**为何在垂直域有效**：信号密度高；**分析与改码可分离**；门禁清晰。

**采纳建议（最高优先级，且与我们设计已对齐）**：

- 保持 Seer 式阶段机与 artifact
- Excel 缺陷尽量补齐：**堆栈、页面、复现、仓库、版本**（Dify 校验）
- 低置信停止；Verify≈我们的「本地 CI」
- MR 后可选二期：拉流水线失败再 `pr_iteration`

---

### 3.11 垂直开源：Mangonaut / Samba / sentry-claude-auto-pr

| 项目 | 模式 | 可学点 |
|------|------|--------|
| Mangonaut | Sentry webhook → Claude 探仓 → PR | 置信度过滤、snippet 级替换、安全校验 |
| Samba | 最小改动流水线 | parse→locate→propose→commit→PR 确定性步骤 |
| sentry-claude-auto-pr | clone + Claude Code CLI → PR | 与我们「本地 clone + coding agent」同构但缺分层与验证门禁 |

**采纳**：交付层学 Samba 的确定性 git/MR；质量层必须超过它们（加 Verify + 分层）。

---

## 4. Harness 效应：跨系统共性（提炼）

来自论文 *Beyond the Model…* 与上述系统交叉验证：

### 4.1 什么真正涨分

| 组件 | 效果倾向 |
|------|----------|
| **结构化工具**（read/edit/glob 等） | 稳定正向 |
| **任务专用 subagent**（定位/实现/测试） | 稳定正向 |
| **显式规划** | 有帮助，但非越大越好 |
| **通用 subagent 乱加** | 可能负向（协调税） |
| **激进 context compression** | 仓库级任务可能负向 |
| **复杂 harness × 强模型 × 开放任务** | 放大器 |
| **复杂 harness × 弱模型 × 固定修 bug** | 补偿器；强模型边际收益下降 |

### 4.2 「效果好」的统一公式

```text
高质量修复 ≈
  足够的缺陷/仓库信号
+ 层次化定位（少盲搜）
+ 方案与改码解耦（architect / editor）
+ 执行反馈闭环（测试真值 > LLM 自评）
+ 多样本或对抗审查（选优 / 找漏）
+ 交付门禁（不过测不开 PR）
+ 克制工具与上下文（干净观测）
```

### 4.3 反模式

- 单次超长会话既分析又改码又自评
- 无测试门禁的「看起来修好了」
- 把 push/MR 交给模型自由发挥
- 为刷榜过度拟合 SWE 隐藏测试（我们有真实本地测试，应以此为真值）
- 无边界的 Bash 与无 Scope 的全仓重构

---

## 5. 与我们当前设计的对照

| 我们已有设计 | 对标 | 评价 |
|--------------|------|------|
| Dify 一次整表 + Agent 聚合 | Seer 批处理 / 工业 triage | ✅ 正确；补强指纹与 Scope |
| 一簇一 MR | 工业常见「一 issue 一 PR」扩展 | ✅；过大簇要拆 |
| RootCause→Plan→Implement→Verify | Seer / Agentless / SpecRover | ✅ 核心应对齐加固 |
| GREEN 硬门禁 | SWE 真值测试 / Aider retry | ✅ **最大差异化优势** |
| 自动探测 + userPrompt | Profile / skills | ✅ |
| Claude Agent SDK 改码 | Pi / Claude Code 工具集 | ✅ |
| Orchestrator 确定性 push+MR | Samba / 旧仓 publish | ✅ |
| 无内置业务库、run 目录文件态；可选外部 API 同步 | 本地优先 + 可插拔远程 | ✅（StorageAdapter） |
| 内置精选 Skills + 模型按需调用 | Claude Skills / NanoHarness Lazy Skills | ✅（设计 §7） |
| 可配置 MCP 挂载与白名单调用 | Claude Agent SDK mcpServers；旧仓 GitLab/监控 MCP | ✅（设计 §8） |
| Stack Profile 可扩展 | Moatless flows | ✅ |

**缺口（相对 SOTA，建议补）**：见下一节采纳清单。

---

## 6. 设计采纳清单（站在巨人肩膀上）

### P0 — 一期必须纳入（改设计/实现规格）

1. **层次化 Localization artifact**（学 Agentless）  
   - `suspectFiles[]` → `suspectSymbols[]` → `editTargets[]`  
   - 进入 Implement 的 prompt 必须带这些边界

2. **测试真值 > 模型自评**（学 SWE / pi-bench）  
   - Verify 失败不得开 MR（已有）  
   - 报告里强制贴 **命令、exit code、失败摘要**

3. **Edit 反馈环**（学 SWE-agent ACI）  
   - Implement 后自动 `node --check` / `vue-tsc` / eslint（按 Profile）  
   - 新引入错误才阻断，并回灌 agent

4. **Architect–Editor 分离**（学 Aider / Seer handoff）  
   - RootCause/Plan 禁用写工具；Implement 才开 Edit  
   - Plan 验收标准写入 Verify 检查清单

5. **确定性交付**（学 Samba）  
   - commit/push/create MR 永不交给自由 Bash

6. **低置信停手**（学 Seer fixability）  
   - 定位空洞 / 方案空泛 / 无探测到 test → `skipped_no_mr` + 原因

### P1 — 强烈建议（质量跃迁）

7. **轻量 Repo Map**（学 Aider）  
   - 每仓缓存 outline，注入分析阶段

8. **多样本选优（难簇）**（学 Agentless / OpenHands）  
   - N=2~3 worktree 并行或串行；以 Verify 选最优；预算开关

9. **独立 Reviewer 步**（学 SpecRover / Claude adversarial / pi-company）  
   - 只读 diff + Plan；输出 `approve | request_changes`  
   - `request_changes` 触发 Iterate，不直接 MR

10. **Reproduction 辅助**（学 Agentless）  
    - 能写则写最小复现测试；不能写则强制「手工复现步骤」进 MR 描述

11. **失败日志结构化回灌**（学 Seer pr_iteration）  
    - Iterate prompt 只含失败相关片段，避免整日志污染上下文

### P2 — 二期 / 可选

12. Inference-time Critic 模型（OpenHands 研究向）→ 先用规则+LLM judge  
13. SBFL / 动态频谱定位（需可靠失败测试）  
14. Dynamic Workflows 脚本化编排（若 SDK 版本支持且值得）  
15. Hermes 式跨会话记忆 / skills hub（与「无存储」冲突，仅可选本地 skills 文件）  
16. MR 创建后监听 GitLab CI 再 iterate

### 明确不采纳或延后

| 项 | 原因 |
|----|------|
| 纯 bash-only mini harness 作为产品默认 | 我们已有 SDK 结构化工具，且要控权 |
| Hermes 全量个人助手平台 | 范围过大，违背无状态执行器 |
| 无验证的 webhook→PR 捷径 | 质量目标冲突 |
| 过度压缩对话历史 | 实证可能伤仓库任务；优先落盘 |

---

## 7. 建议修订后的「质量黄金路径」（综合版）

```text
Defects[] (Dify)
  → Normalize + Aggregate（簇）
  → Repo prepare（clone + Profile detect + install）
  → [每簇]
       Localization（层次化，只读）
       RootCause artifact
       Solution Plan + 验收标准（只读）
       gate: fixability & scope
       Implement（SDK，可 N 候选）
       Static check（lint/tsc）
       Verify（仓库测试 = 真值）
       Reviewer（可选 P1）
       gate: GREEN && review.approve
       GitLab push + MR
  → Report.json → Dify
```

与初版设计相比，**新增强调**：Localization 产物、静态检查环、难簇多样本、独立 Reviewer、fixability 门禁细化。

---

## 8. 风险与评测建议

| 风险 | 缓解 |
|------|------|
| 聚合错簇导致错误大 MR | 簇大小上限；跨模块强制拆分 |
| monorepo 测错包 | Profile + userPrompt 覆盖；探测结果入报告供纠偏 |
| Electron E2E 过重 | 默认单测；E2E 需 prompt 显式 |
| 成本爆炸（多样本） | 仅低置信/失败簇开启；并发上限 |
| 模型刷「假绿」 | 测试命令由 Orchestrator 跑，不由模型声称 |

**内部评测集（建议）**：

- 10~20 个真实历史缺陷（已合并 MR 作 oracle）
- 指标：GREEN 率、开 MR 率、人审一次合并率、平均改动行数、耗时/费用
- 对照：单次 SDK 一把梭 vs 完整流水线（A/B）

---

## 9. 参考链接（精选）

- SWE-bench Verified: https://www.swebench.com/verified  
- mini-SWE-agent: https://github.com/SWE-agent/mini-swe-agent  
- SWE-agent ACI 论文: https://arxiv.org/abs/2405.15793  
- Agentless: https://github.com/OpenAutoCoder/Agentless · https://arxiv.org/abs/2407.01489  
- AutoCodeRover / SpecRover: https://arxiv.org/html/2404.05427 · https://arxiv.org/html/2408.02232  
- OpenHands scaling: https://www.openhands.dev/blog/sota-on-swe-bench-verified-with-inference-time-scaling-and-critic-model  
- Harness Effects 论文: https://arxiv.org/html/2609.32459  
- Aider repo map / SWE: https://aider.chat/docs/repomap.html · https://aider.chat/2024/05/22/swe-bench-lite.html  
- Sentry Autofix: https://docs.sentry.io/product/ai-in-sentry/seer/autofix/  
- Claude Dynamic Workflows: https://code.claude.com/docs/en/workflows  
- Pi coding agent: https://github.com/badlogic/pi-mono  
- Hermes Agent: https://github.com/NousResearch/hermes-agent  
- Mangonaut: https://github.com/mango1135/mangonaut  

---

## 10. 结论

缺陷修复「效果好」的现代系统，赢在 **harness：定位结构、阶段门禁、执行真值、选优与对抗验证**，而不是更长的自由 agent 环。

我们的本地 + Dify + 聚合簇 + Claude Agent SDK + GREEN→GitLab MR 路线，已经站在正确的产业范式上（最接近 **Seer 分析流水线 × SWE 验证真值 × Claude/Pi 改码工具**）。下一步应把本报告 **P0/P1 采纳清单** 写回设计规格并进入实现计划，而不是平行再造 SWE-agent 或 Hermes。
