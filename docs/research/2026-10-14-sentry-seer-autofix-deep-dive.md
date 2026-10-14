# Sentry Seer Autofix 深度源码分析报告

> 日期：2026-10-14  
> 目的：从 **getsentry/sentry** 公开仓中 Seer/Autofix 相关实现，提炼与本地 BugFix Agent **高契合** 的编排与质量机制，支撑设计落地  
> 对照设计：[`docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md`](../superpowers/specs/2026-10-14-local-bugfix-agent-design.md)  
> 总调研：[`2026-10-14-sota-bugfix-agent-survey.md`](./2026-10-14-sota-bugfix-agent-survey.md)  
> 源码快照：`docs/research/_seer_raw/`（本报告撰写时从 `getsentry/sentry` raw 拉取）

---

## 0. 结论先行

Seer Autofix 与我们的契合点**极高**，但有一处**产品级刻意分歧**（已写入设计 G13/G14）：

| | Seer | **我们（日批全自动）** |
|--|------|------------------------|
| 中途停止 | 支持 `stopping_point`：只到根因/方案，**等人继续** | **不做**产品级中间断点；不等人回复 |
| 可修结局 | 可配置停在改码或开 PR | **可修 ⇒ 一律尝试走到开 MR** |
| 不可修结局 | 停在分析或不开自动化 | **仍必须完整报告**（原因 + 已有分析） |
| 主交付 | Issue 页交互 + 可选 PR | **Run 汇总报告**：已修+`mrUrl` / 未修+说明 |

其余同构关系：

| Seer | 我们的设计 |
|------|------------|
| 分步流水线（内部阶段） | Aggregate 后每簇：Analyze→Implement→Verify→MR（**一次跑完**） |
| 数值 `fixability_score` + tuning | 决定「可修路径 vs 未修复报告」，**不是**「停在哪等人」 |
| RootCause `fixability` 三态 | 不可修 → 写未修复报告；可修 → 继续到 MR |
| `on_completion_hook` 自动步进 | Orchestrator 自动步进（无人工审批门闩） |
| Coding agent handoff | Claude Agent SDK Implement |
| Group / Supergroup | 缺陷聚合 → **一簇一 MR** |
| PR iteration | Verify 失败自动 Iterate；二期可接 GitLab CI |
| `should_run_repo_checks` | Stack Profile + GREEN 硬门禁 |
| 永不默认 merge | 永不自动 merge |

**架构事实必须说清**：公开仓 `getsentry/sentry` 主要是 **控制面**（触发、门禁、配额、hook、hand-off、PR 迭代编排）。真正的 RCA/Solution LLM 行为大量在私有服务 **Seer**（`FEATURE_ID=autofix`，payload 发到 Seer Agent）。`prompts.py` 里 `root_cause_prompt` / `solution_prompt` 直接 `raise RuntimeError("…must run through the Seer Autofix feature")`。因此本报告对「模型怎么想」只能从 **Sentry 侧契约、artifact schema、code_changes prompt、hook 行为** 反推；对「怎么编排、怎么门禁」则可从 Sentry 源码**精确还原**。

---

## 1. 系统边界与模块地图

### 1.1 双进程架构

```text
┌──────────────────────────── Sentry（公开仓） ────────────────────────────┐
│ 触发：API / post_process / night_shift / Slack / MCP / PR comment         │
│ 门禁：fixability_score、automation_tuning、quota、rate limit、已有 run    │
│ 编排：trigger_autofix_agent → feature.dispatch → SeerAgentClient          │
│ Hook：AutofixOnCompletionHook（步进、handoff、push PR、introspection）     │
│ 交付：push_changes / coding_agent_handoff / PR iteration 队列             │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ feature payload + on_completion_hook
                                   ▼
┌──────────────────────────── Seer（私有服务） ────────────────────────────┐
│ 执行：root_cause / solution / code_changes / pr_iteration agent 环        │
│ 产出：结构化 artifact、file_patches、run state                            │
│ 完成后回调 Sentry on_completion_hook（含失败也可 call_on_failure）         │
└──────────────────────────────────────────────────────────────────────────┘
```

对应我们：

- **Dify + Orchestrator** ≈ Sentry 控制面（触发、门禁、步进）
- **Claude Agent SDK** ≈ Seer 执行面（或 Seer 的 coding handoff 目标）
- **本地 Verify** ≈ Seer 的 `should_run_repo_checks` + 我们更强的 GREEN 硬门禁

### 1.2 Sentry 侧关键文件（本报告精读）

| 路径 | 职责 |
|------|------|
| `seer/autofix/steps.py` | 步骤枚举与 stopping_point→step 映射 |
| `seer/autofix/constants.py` | Fixability 阈值、automation tuning、状态、referrer |
| `seer/autofix/artifact_schemas.py` | RootCause / Solution / FixabilityAssessment schema |
| `seer/autofix/autofix_agent.py` | STEP_CONFIGS、trigger、handoff prompt、push |
| `seer/autofix/feature/dispatch.py` | 向 Seer 启动/继续 feature run |
| `seer/autofix/feature/models.py` | Feature payload、RepoPins、各步 args |
| `seer/autofix/on_completion_hook.py` | 步进、fixability introspection、handoff、开 PR |
| `seer/autofix/issue_summary.py` | 摘要、fixability score、自动化准入与 stopping 选择 |
| `seer/autofix/prompts.py` | code_changes / pr_iteration 提示词（RCA/Solution 在 Seer） |
| `seer/autofix/utils.py` | StoppingPoint、automation settings、限流 |
| `seer/autofix/coding_agent*.py` | 外部 coding agent handoff 与状态同步 |
| `seer/autofix/autofix.py` | Trace tree、tags overview 等上下文增强 |
| `seer/supergroups/lightweight_rca_cluster.py` | 轻量 RCA + embedding 超组聚类触发 |
| `tasks/seer/autofix.py` | 异步：摘要→自动化、只跑自动化、偏好回填 |
| `tasks/seer/pr_iteration.py` | PR 评论/CI/Review 反馈驱动再迭代（大文件） |
| `static/.../stoppingPoint.ts` | 前端 stopping 选项与用户语义映射 |

---

## 2. 流水线设计（最值得抄）

### 2.1 步骤与停止点是两套概念

**步骤 `AutofixStep`**（实际执行单元）：

- `root_cause`
- `solution`
- `code_changes`
- `pr_iteration`（反馈驱动，不在「自动停止点」主链上）

**停止点 `AutofixStoppingPoint`**（自动流水线允许走到哪）：

- `root_cause` / `solution` / `code_changes` / `open_pr`

映射关系（`steps.py`）：

- `open_pr` **不是**独立 Step，而是「做到 code_changes 后，由 hook 再 `push_changes` 开 PR」
- UI 上「Stop after Plan」在部分套餐会把 `solution` 与 `code_changes` **合并展示**（`coaleseStoppingPoint`），降低用户认知负担

**对我们的启示**：停止点应是产品配置；步骤是实现细节。例如用户设「只分析」→ stopping=`plan`；「可开 MR」→ stopping=`open_mr`。Implement 与 Open MR 可以拆成两步，Open MR 由 Orchestrator 确定性执行（与 Seer 一致）。

### 2.2 步进推进器：`AutofixOnCompletionHook`

每步成功结束后：

1. 发 webhook / 分析事件  
2. 读 `metadata.stopping_point`（或 Sentry 侧 mirror extras）  
3. `determine_fixability`（仅 root_cause 步，读 artifact）  
4. 若已达 stopping → **停**  
5. 否则若配置了 coding agent handoff → **交接外部 agent，不再用 Seer 继续改码**  
6. 否则若 stopping=`open_pr` 且刚完成 `code_changes` → **`_push_changes`**  
7. 否则 `_get_next_step` → 再 `trigger_autofix_agent(next_step)`  

失败/超时：hook 仍可能被调用（`call_on_failure=True`），但**不推进主流水线**；PR iteration 会单独 pause/记 outcome。

**对我们的启示**：

- 必须有统一的「阶段完成钩子」，而不是在 LLM 对话里自己决定是否继续  
- 失败不得静默进入下一阶段  
- 「开 MR」与「改码」解耦：改码结束 → 确定性 push/create MR

### 2.3 每步配置表 `STEP_CONFIGS`

```text
ROOT_CAUSE:   artifact=RootCauseArtifact, coding=False, reasoning=medium
SOLUTION:     artifact=SolutionArtifact,  coding=False
CODE_CHANGES: artifact=None（读 file_patches）, coding=True
PR_ITERATION: artifact=None, coding=True, 可开 PR context tools
```

要点：

- **分析步关闭 coding**（`enable_coding=False`）→ 与我们「分析只读 / 实现可写」完全一致  
- **产物 schema 强制结构化**；改码步无强制 JSON artifact，以补丁为准  
- Feature dispatch 里 `enable_coding = step in (CODE_CHANGES, PR_ITERATION)`

### 2.4 Feature Payload 契约

`AutofixFeaturePayload` 统一携带：

- issue 标识：`group_id`, `project_id`, `short_id`, `title`, `culprit`
- `step` + 分步 `step_args`（RCA 可带 `repo_pins`；Solution/CodeChanges 可带 `should_run_repo_checks`）
- `stopping_point`、`user_context`、`on_completion_hook`
- `existing_run_id` / `insert_index`（从某步重跑、截断后续）

**RepoPins**：可钉死仓库 sha/branch，保证修复基线可复现。

**对我们**：每簇 run 应写入 `baseCommit` / `baseBranch`；支持从某阶段 regenerate。

---

## 3. 可修复性（Fixability）——双轨机制（核心）

Seer 实际有 **两套** fixability，职责不同，**不要混为一谈**。

### 3.1 轨 A：数值分 `fixability_score`（自动化准入与走多远）

**来源**：在 issue summary 之后，调用 Seer  
`POST /v1/automation/summarize/fixability`，把摘要写入 `group.seer_fixability_score`（可缓存）。

**阈值**（`FixabilityScoreThresholds`）：

| 枚举 | 分数 |
|------|------|
| SUPER_HIGH | 0.76 |
| HIGH | 0.66 |
| MEDIUM | 0.40 |
| LOW | 0.25 |
| SUPER_LOW | 0.0 |

**由分数建议 stopping_point**（`_get_stopping_point_from_fixability`）：

| 分数区间 | 建议停止点 |
|----------|------------|
| `< 0.40` (MEDIUM) | `None`（不自动跑 / 等价极保守） |
| `[0.40, 0.66)` | 只到 `root_cause` |
| `[0.66, 0.78)` | 到 `code_changes`（**0.76+0.02 buffer，刻意少开 PR**） |
| `≥ 0.78` | 可到 `open_pr` |

**再与用户偏好取更保守者**（`STOPPING_POINT_HIERARCHY` + `_apply_user_preference_upper_bound`）：  
永远不会「分数说开 PR、用户说只到根因」却强行开 PR。

**Automation Tuning**（项目选项 `autofix_automation_tuning`）决定「分数够不够触发自动化」：

| Tuning | 触发条件 |
|--------|----------|
| OFF | 永不自动 |
| SUPER_LOW | score ≥ 0.76 |
| LOW | score ≥ 0.66 |
| MEDIUM | score ≥ 0.40 |
| HIGH | score ≥ 0.25 |
| ALWAYS | 总是（仍受其它门禁） |

**自动化准入全集**（`is_group_eligible_for_automation`）：

1. 有 Seer 权限  
2. **没有**进行中的 live autofix run（防重入）  
3. fixability 过 tuning（或 issue_type 强制 always_trigger）  
4. 配额 `SEER_AUTOFIX`  
5. 项目级 rate limit  

通过后才 `delay` 触发，并在真正触发时再 increment 限流计数。

**对我们的映射（强烈建议原样落地思想）**：

```text
缺陷/簇 → 可修性评分（0~1 或枚举）
       → tuning（用户/Dify 配置：严格/中等/宽松）
       → 决定：跳过 | 只分析 | 改码+验证 | 允许开 MR
       → 与「用户 maxStoppingPoint」取 min（更保守）
```

分数模型一期可用：规则特征（有堆栈？有仓库？有复现？单文件嫌疑？）+ 轻量 LLM 打分；不必一上来复刻 Seer 私有模型。

### 3.2 轨 B：RootCause artifact 内嵌 `FixabilityAssessment`（质检/观测）

Schema（`artifact_schemas.py`）：

```text
assessment: "fixable" | "needs_more_context" | "not_actionable"
reason: string
```

在 **root_cause 步完成** 时，`determine_fixability`：

- 用 Pydantic 校验 artifact（不合 schema 则跳过，容错）  
- 记录 analytics / log（introspection）  
- **当前 Sentry hook 主要做观测，不在此处直接砍流水线**（流水线仍由 stopping_point 控制）

但产品语义上它表达了：「根因是否值得继续写代码」。

**对我们的映射（建议比 Seer 更硬）**：

- `not_actionable` / `needs_more_context` → **禁止进入 Implement**，只出报告  
- `fixable` 才允许 Implement  
- 与轨 A 数值分叠加：任一失败则收紧

### 3.3 为何「双轨」好

| | 轨 A 数值分 | 轨 B 根因内嵌评估 |
|--|-------------|-------------------|
| 时机 | 流水线**前** | 根因步**后** |
| 作用 | 省钱/控噪/决定走多远 | 对「这次根因」再质检 |
| 输入 | issue summary | 完整 RCA 上下文 |

我们做批量 Excel 缺陷时，轨 A 过滤「别开修」；轨 B 防止「根因胡扯仍改码」。

---

## 4. 结构化 Artifact（质量合同）

### 4.1 RootCauseArtifact

字段设计非常「可评审」：

| 字段 | 作用 |
|------|------|
| `headline` ≤12 词 | 人可读标题，禁乱格式 |
| `one_line_description` | 一句话根因 |
| `five_whys[]` | 因果链，逼模型讲清「为什么」 |
| `reproduction_steps[]` | 复现 |
| `relevant_repo` | **锁定应改的仓库**（handoff/选仓用） |
| `fixability` | 三态可修性 |

### 4.2 SolutionArtifact

- `one_line_summary`
- `steps[]`：每步 `title` + `description`（短、可执行）

### 4.3 Code changes

- **无**强制 JSON artifact  
- 以 `file_patches` / 工作区 diff 为准  
- Prompt 强调：基于已有根因与方案；**最小改动**；若曾改过则**推倒重来**（避免脏状态）

### 4.4 Handoff Prompt 组装

`generate_autofix_handoff_prompt` 把 root_cause + solution 拼成给 Cursor/Claude/Copilot 的提示，并强制：

- PR 描述基于**实际实现**而非「空想方案」  
- 标明 Seer handoff  
- 带 Fixes 链接  

**对我们**：Implement 阶段 system/user prompt 应注入上一阶段 artifact JSON；MR 描述模板同构。

---

## 5. Issue「聚合」在 Seer 体系里是什么

用户关心的「缺陷聚合」，在 Sentry/Seer 里分层存在：

### 5.1 Group（Issue）——已是事件聚合

Sentry 原生把多个 event 归入一个 Group（指纹/规则）。Autofix **以 Group 为原子**，不是单条 event。

### 5.2 Supergroup + Lightweight RCA Cluster——跨 Issue 根因簇

`trigger_lightweight_rca_cluster(group)`：

1. 取 latest event，要求 **有 stacktrace**  
2. 平台不在 `SEER_INELIGIBLE_EVENT_PLATFORMS`  
3. 把序列化 issue+event 发给 Seer `LightweightRCAClusterRequest`  
4. Seer 侧做轻量 RCA + **embedding 相似度聚类进 supergroups**

这是「同一根因的多个 Issue 合成超组」——与我们「Excel 多行聚成一簇」**目标一致、信号不同**（他们靠堆栈嵌入；我们靠描述/堆栈/模块/指纹规则）。

### 5.3 对我们聚合设计的可抄点

| Seer 做法 | 我们可落地 |
|-----------|------------|
| 无堆栈则跳过聚类 | 无关键字段的缺陷降级为「单条簇」或不修 |
| 平台黑名单 | Stack Profile 不支持则标记 skip |
| 轻量 RCA 后再聚类 | 可先粗聚类，再对簇做 RootCause，必要时拆簇 |
| 一 Group 一 autofix run，防重入 | 一簇一 run；同簇进行中去重 |
| `relevant_repo` 锁仓 | 簇必须绑定单一主仓库；跨仓则拆簇 |

**注意**：Seer 自动化主路径仍是「一 Group 一流水线」；supergroup 更偏 triage/探索。我们产品主路径是「批量→簇→一簇一 MR」，聚合权重应比 Seer 更高，但**门禁思想一致**。

---

## 6. 上下文增强（为何垂直域更强）

`autofix.py` 等展示 Seer 修复前的信号密度：

- **Trace tree**：按 event 拉完整 trace（超时保护，默认 15s；Web Vitals 放宽时间窗）  
- **Tags overview**：聚合 tag 分布，排除无信息 tag（replay_id、level 等）  
- Issue summary + 序列化 event（堆栈、culprit、title）  
- 代码映射 / repo 连接（settings 里 `reposCount`）

**对我们**：Excel 缺陷应尽量对齐 Context Pack 字段（堆栈、页面、仓库、版本、复现）；Dify 校验阶段补齐。信号越瘦，fixability 应越低。

---

## 7. Coding Agent Handoff（与我们 SDK 封装同构）

设计意图（文档与代码一致）：

- Seer **擅长**根因与方案（富 Sentry 上下文）  
- **改码**可交给 Claude Code / Cursor / Copilot  
- Handoff 点通常在 root_cause 完成后（配置 `automation_handoff`）  
- 可 `auto_create_pr`；也可只给方案让外部开 PR  

Sentry 侧还负责：

- 记录 `SeerRunCodingAgentHandoff`  
- 轮询外部 agent 状态、回写、关联 PR  

**对我们**：不必自建「第二种改码引擎」；Orchestrator 分析 + SDK 实现 = 内嵌 handoff。若未来要接 Cursor Cloud，可复用同一 artifact 合同。

---

## 8. 仓库自检：`should_run_repo_checks`

`code_changes_prompt` 在开启时明确要求：

1. 先 install/setup（checkout **默认无依赖**）  
2. 对改动文件跑 lint/format  
3. 跑相关测试，大仓要缩小范围  
4. 失败则修到过  
5. **命令来源**：README / Makefile / package.json / CI——**禁止瞎猜**  
6. 跑不了要如实报告，**禁止谎称通过**

这与我们「本地意义 = 能跑验证」几乎逐字对齐；我们比 Seer 默认更强：**Verify 由 Orchestrator 跑，作硬门禁**。

Agentic triage（night_shift）还可强制 bash mode + repo checks feature flag。

---

## 9. PR Iteration（反馈闭环）

`tasks/seer/pr_iteration.py` 体量很大，职责包括：

- 消费 PR **评论 / Review / Check Suite** 反馈队列  
- 权限不足时评论说明  
- 触发 `pr_iteration` 步继续改  
- pause、cap 耗尽交接、sweep 细节  
- 迭代完成 webhook、reactions  

产品含义：**开 PR 不是终点**，CI 与人审可再驱动一轮最小修改。

**对我们一期**：本地 Verify Iterate 已覆盖「测试反馈」。二期可加 GitLab MR note / pipeline webhook → 再入队 Iterate（对标 pr_iteration）。

---

## 10. 其它值得抄的工程细节

| 点 | 说明 | 我们怎么用 |
|----|------|------------|
| Referrer 全链路打标 | API/Slack/MCP/post_process/night_shift/… | Dify/手动/重跑来源写入 report |
| Quota + Rate limit | 自动化不拖垮成本 | 本地也可限并发簇数、日限额 |
| Draft PR 选项 | `should_open_autofix_pr_as_draft` | GitLab MR 可先 WIP/Draft |
| insert_index 截断重跑 | 从中间步 regenerate | 支持「只重跑 Implement」 |
| enable_seer_coding 总开关 | 可禁改码只分析 | 对应我们 stopping 配置 |
| 分析事件分步 started/completed | 可观测 | 簇进度 phase 事件 |
| Artifact 校验失败容错 | ValidationError 不崩 hook | 解析失败 → 该簇失败报告 |
| 开 PR 前检查 has_code_changes / is_synced | 无 diff 不开 PR | 同我们 AGENT_NO_CHANGES |
| relevant_repo 选仓 | 多仓项目锁一仓 | 一簇一仓；多仓拆簇 |

---

## 11. Seer 未在公开仓暴露、但需知情的部分

以下在 **私有 Seer** 内，Sentry 只传契约：

- RootCause / Solution 的完整 system prompt 与工具环  
- Fixability **模型**如何从 summary 出 0~1 分  
- Lightweight RCA embedding 与 supergroup 算法细节  
- Explorer / bash 工具具体实现  

我们落地时应用 **自有 prompt + SDK 工具 + 本地测试真值** 填补，不必等待 Seer 开源。

---

## 12. 针对本项目的「逐条采纳规格」

### 12.1 必须采纳（P0）

1. **内部步骤机 + 自动完成钩子**（抄 on_completion_hook 的自动步进；**不抄**对人停等的 stopping_point 产品语义）  
2. **双轨 Fixability**：跑前评分 + 根因三态 → 只决定「走修码」还是「写未修复报告」  
3. **Artifact 合同** + **可修必须尝试开到 MR**  
4. **分析禁 coding / 实现开 coding**  
5. **Open MR 与改码解耦**，确定性 push+create MR  
6. **无 diff / 验证失败 / 不可修 → 不开 MR，但写全报告**  
7. **命令探测优先读仓内脚本**  
8. **一簇一 run 去重**  
9. **Run 汇总报告**：`fixed[]`（含 mrUrl）+ `unfixed[]`（含完整原因）

### 12.2 强烈建议（P1）

10. Automation tuning（严格/中等/宽松）只影响「多容易被判可修」，不引入中途等人  
11. Handoff 式 Implement prompt（拼 artifact）  
12. Repo pin：`baseCommit`  
13. Draft/WIP MR 选项  
14. 报告 introspection：assessment、score、skills/mcp  

### 12.3 二期

15. GitLab CI / MR 评论驱动的 pr_iteration  
16. 跨缺陷 embedding 聚类  
17. Trace/tag 级富信号  

### 12.4 明确不照搬

- **产品级 stopping_point 等人继续**（与日批全自动冲突）  
- Seat/用量计费、私有 Seer 服务、GitHub Check Suite 全套  

---

## 13. 推荐落地流水线（全自动双结局）

```text
Dify 日批 defects[]
  → Normalize → Aggregate → clusters[]
  → 每簇（不等用户）:
       FixabilityScore (轨A)
       → Localization → RootCause (+ 轨B)
       → 不可修 → unfixed[] 完整说明 → 下一簇
       → 可修 → Solution → Implement → Verify → Iterate*
            → GREEN → push + MR → fixed[] { mrUrl }
            → 失败 → unfixed[] 完整说明（含分析产物）
  → 汇总 Report → Dify / 远程 StorageAdapter
```

---

## 14. 总结

Seer 教给我们的是 **工业级自动步进与可修性门禁**；我们与之分流的是 **日批全自动双结局**——可修直达 MR，不可修也给完整报告，不做根因后等人。再叠加本地 GREEN 与批量聚合，形成差异化。

建议：设计规格已用 G13/G14/§5 固化该分歧；实现按「双结局报告」为验收标准。

---

## 附录 A：关键常量速查

```text
FixabilityScoreThresholds: SUPER_HIGH=0.76 HIGH=0.66 MEDIUM=0.40 LOW=0.25
OPEN_PR buffer: SUPER_HIGH + 0.02 = 0.78
STOPPING_POINT_HIERARCHY: root_cause=1 < solution=2 < code_changes=3 < open_pr=4
FixabilityAssessment: fixable | needs_more_context | not_actionable
FEATURE_ID: "autofix" (legacy: "autofix_rca")
```

## 附录 B：源码引用索引

- Steps: `src/sentry/seer/autofix/steps.py`  
- Artifacts: `src/sentry/seer/autofix/artifact_schemas.py`  
- Fixability score & automation: `src/sentry/seer/autofix/issue_summary.py`  
- Hook pipeline: `src/sentry/seer/autofix/on_completion_hook.py`  
- Agent trigger & handoff prompt: `src/sentry/seer/autofix/autofix_agent.py`  
- Feature dispatch: `src/sentry/seer/autofix/feature/dispatch.py`  
- Code changes prompt / repo checks: `src/sentry/seer/autofix/prompts.py`  
- Clustering trigger: `src/sentry/seer/supergroups/lightweight_rca_cluster.py`  
- Context: `src/sentry/seer/autofix/autofix.py`  
