# 报告型分析 Agent：落地前决策备忘

> 基线：`main` @ `9ced3dd`（2026-10-23）。
> 前置依据：[报告型分析 Agent 设计](2026-10-23-report-agent-design.md)（`BOUND-*` / `CONF-*` / `DEC-24..28`）、[缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)、[目标流水线设计](2026-10-22-target-pipeline-design.md)、[环境适配层与能力降级](2026-10-22-environment-adapter-and-capability-degradation.md)。
> 定位：本文是**阅读四份设计文档后、动手改代码前**的整理稿。回答四件事：① 我对新方向的理解判断；② 哪些点必须由产品负责人拍板（`Q-*`）；③ 哪些点我不确定、需要补信息（`U-*`）；④ 我的建议与落地顺序。**不含实现**。
> 编号约定：`Q-*` 需决策、`U-*` 不确定、`J-*` 理解判断、`R-*` 建议。后续实现任务引用这些编号。
>
> **⚠️ 跟进（2026-10-29）**：`Q-7` / `Q-8` / `U-4` / `U-5` 已有方向性答复（LangGraph **Python** 全量 + Claude Code；SWE 全删；缺陷走业务 MCP、过渡期 xlsx；版本 tag 可选）。详见 [决策跟进分析](2026-10-23-report-agent-decision-followup.md)。本文保留原文，以跟进文的 `ANS-*` / `IMP-*` / `NQ-*` 为准。

---

## 0. 结论先行

| 项 | 内容 |
|---|---|
| 对新方向的总判断 | ✅ 成立且自洽。砍掉修复侧后，产品从"BugFix Agent"变为"缺陷单蒸馏 + 代码级分析报告"，读者是业务侧 agent |
| 最大收益 | 只读 Agent 不需要 install / 起服务 / 跑测试；业务环境 8 类异构里 6 类对本产品不再成立；可高并发、可用更便宜的模型 |
| 现有代码可复用 | 约 **55~60%**（基础设施 + analyze 骨架 + agent/* + store），修复侧约 35~40% 退役 |
| 必须先拍板的决策 | **5 项**：`Q-1` CLAUDE.md 重写、`Q-2` 蒸馏层进范围、`Q-4` 报告物理布局、`Q-7` 双引擎去留、`Q-8` SWE-bench 适配器与修复侧 skills 去留 |
| 可在实现中自行决定的 | `Q-3` / `Q-5` / `Q-6` / `Q-9` / `Q-10`（给出默认选项，不反对即按默认） |
| 落地顺序 | 契约与置信度 → 蒸馏层（0 LLM）→ 定位基础设施 → analyze 重写 → 渲染 → 退役 |

---

## 1. 我的理解判断（`J-*`）

### J-1 四份文档是一条递进链，不是四个并列提案

```
10-22 输入契约     缺陷单长什么样：无栈、无 URL、唯一信息源是描述文本；43% 不需改码
   ↓
10-22 目标流水线   S0..S10 / CLS-1..6 / LOC-L0..L5 / scopeHint —— 分析侧设计全部保留
   ↓
10-22 环境适配层   EnvironmentProfile；本产品只消费 localization + capabilities
   ↓
10-23 报告型 Agent 在前三者之上砍掉修复侧，把"报告"升格为产品本体
```

读的时候要注意：10-22 的三份文档**没有被废弃**，只是其中"改码 / 验证执行 / 交付"的章节降为"下游修复 agent 的参考流程"。分析侧（`S0..S6`、`CLS-*`、`LOC-*`、`scopeHint`、`localization`）仍然是实现依据。

### J-2 为什么"去掉 fixability gate"是对的

技术上：gate 的作用是拦住不该进 `prepare/verify/deliver` 的簇，这三段没了，gate 没有可 gate 的对象。
产品上：判断"能不能修"是业务侧的决策权。我们越权判定会产生两种错误——把能修的判成不能修（漏报），把不能修的判成能修并编造因果链（更糟）。

替代物 `confidence` + `suggestedAction` 的本质是**从"二元裁决"变成"排序 + 路由"**：不丢条（`BOUND-2`），每条都出报告，但告诉下游"先看哪个、走哪条流程"。

### J-3 置信度必须靠代码压，不能靠模型自评

现有 `src/pipeline/analyze.ts` 的 prompt（第 56-96 行）和 `src/agent/artifacts.ts` 的 `FixabilityAssessmentSchema` 把判定权完全交给模型一次自评，代码侧只有枚举映射（`fixability.ts` 无任何条件分支）。这正是 10-22 `GAP-F1..F5` 指出的问题。

10-23 的 `CONF-1..7` 是对症的：路径不存在→强制 low；引用文件 >3→最多 medium；`expectedBasis=code-inference`→最多 medium。全部可计算、可单测、零 LLM。这与 `docs/agent-harness-design-notes.md` 第一条"让错误在结构上难以发生，而不是在 prompt 里提醒"是同一思路。

### J-4 报告里最值钱的不是结论，是过程

`handoff.ruledOut` + `openQuestions` + `toUpgradeConfidence`（`BOUND-3` 必填）。业务侧 agent 二次分析最贵的不是"再读一遍代码"，而是**重新试错那些走不通的路径**。如果报告只给结论不给过程，下游仍要重走一遍，Token 经济学（10-23 §7）就不成立。

### J-5 "缺陷单蒸馏"是整条链的上游，但 10-23 的差量表漏了它

用户表述的"缺陷单蒸馏"对应 10-22 输入契约 §3 的内容：

| 蒸馏动作 | 依据 |
|---|---|
| 两种描述模板（用例式 / 自由式）拆解为 `实际结果` / `预期结果` / `操作步骤` / `补充：` / `初步定位` | `OBS-7`、§3 语义映射 |
| `补充：` → 影响范围（常是最关键的范围信息） | §3 |
| `初步定位` 仅当值 ≠ "无" 时采纳（按值不按 key） | B 档字段表 |
| 剥离模板占位残留（`问题：1.2.` / `建议：…如其他项目或产品中存同样缺陷，请说明`） | §3 数据清洗项 |
| HTML 实体解码、`\xa0` 归一化 | §3 数据清洗项 |
| `descriptionTooThin`（描述 === 标题 或长度 < 40）作为可计算信号 | `OBS-7` |
| 模块取值优先级：`标题[]前缀` > `测试模块` > `所属模块` | `INV-2` |
| 111 列 Excel 别名表（三套导出变体） | 附录 B / C |

10-22 §10 把它列为"新增 `readers/description`"，10-23 §9 差量表没再提。我判断这是**遗漏而非有意删除**——没有蒸馏层，`prefilter` 的规则分类和 `analyze` 的 prompt 都在裸文本上工作，分析质量上限被输入质量锁死。见 `Q-2`。

### J-6 只读带来的简化尚未被充分利用

既然不改码，且 `workDir` 已是仓库（`C-1`），则：

- **不需要 clone，不需要 worktree**。`src/workspace/git.ts` 只需保留 `git log` / `git diff <tag>` / `rev-parse` 等只读操作服务 `scopeHint`。
- **并发不再有抢锁问题**。10-22 §10 的 `GAP-W3`（共享 `.git` 抢锁）、`GAP-W4`（worktree 不回收）、`GAP-W5`（每 worktree install）、`GAP-W6`（端口冲突）全部消失；只剩 `GAP-W1/W2`（`updateRunMeta` 竞态、`writeJson` 非原子）。
- **Agent SDK 工具集收窄为 `Read / Glob / Grep`**，`ANALYZE_WRITE_DENY` 变成常态而非特例。

### J-7 现有代码的实际复用面（按文件核对）

| 分类 | 文件 | 说明 |
|---|---|---|
| **直接保留** | `http/app.ts`、`runs/create-run.ts`、`runs/store.ts`、`agent/sdk-runner.ts`、`agent/json-extract.ts`、`mcp/load-config.ts`、`skills/manifest.ts`、`storage/*`、`workspace/paths.ts`、`config.ts`、`cli.ts` | 基础设施，与修复无关 |
| **保留但改语义** | `pipeline/analyze.ts`、`agent/artifacts.ts`、`pipeline/localization.ts`、`pipeline/repo-map.ts`、`pipeline/aggregate.ts`、`pipeline/normalize.ts`、`pipeline/report.ts`、`types.ts`、`workspace/git.ts`（只读化）、`runs/runner.ts`（砍到 `analyze` 为止）、`pipeline/failure-modes.ts` | 见 10-23 §9 |
| **退役** | `pipeline/implement.ts`、`verify.ts`、`verify-classify.ts`、`static-check.ts`、`baseline.ts`、`review.ts`、`scope-lock.ts`、`deliver.ts`、`prepare.ts`、`known-issues.ts`、`log-snip.ts`、`fixability.ts`（改为 `evidenceCompleteness` 采集）、`gitlab/client.ts`、`profiles/*`、`util/exec.ts`、`workspace/diff.ts`、`pipeline/cluster-meta.ts`（大部分字段失效） | 修复侧 |
| **待决策** | `graph/*`（590 行 cluster-graph 是修复流程镜像）、`adapters/swe-bench/*`、`skills/` 中修复侧 5 个 | 见 `Q-7` / `Q-8` |

`runs/runner.ts::processCluster`（757 行文件）从第 290 行 `resolveVerifyPlan` 起到第 672 行全部是修复循环，约占该文件 70%。

### J-8 测试面变化

`test/unit/` 28 个文件中，随模块退役的约 12 个：`deliver-branch`、`scope-lock`、`static-check`、`verify-classify`、`verify-exec`、`iterate-budget`、`review`、`baseline`、`profile-detect`、`pkg-manager`、`exec-timeout`、`fixability`。`test/integration/runner-dual-outcome` 与 `runner-quality-gates` 的断言对象（fixed/unfixed、GREEN 门禁）不再存在，需换成"报告契约 + 置信度降级"断言。`swe-adapter.test.ts` 随 `Q-8` 决定。

### J-9 harness 笔记对本项目的直接映射

`docs/agent-harness-design-notes.md` 是参考资料。对我们最相关的几条：

| pi 的做法 | 对我们的映射 |
|---|---|
| 错误在结构上难以发生（唯一原文匹配、路径校验） | `CONF-1` 路径存在性校验、`CONF-5` 定位为空强制 low |
| 截断输出自带"如何继续" | 三层报告 + L3 分文件 + `detailPath` |
| 压缩摘要固定 schema + 机器提取的文件清单 | 6 段报告 + `localization.primary` 由代码校验，不信模型 |
| skill 只声明元数据按需读 | `sdk-runner.ts` 已这么做，保留 |
| 工具暴露分级 | 分析侧只需 `Read/Glob/Grep`，`LOC-R` 可用 hook 硬拦截（见 `Q-6`） |

---

## 2. 需要你决策的点（`Q-*`）

> 标注 **[必须先定]** 的是动手前必须拍板的；其余给出默认选项，不反对即按默认执行。

### Q-1 【必须先定】`CLAUDE.md` 重写

**现状**：`CLAUDE.md` 仍写"核心硬门禁：**没有 GREEN，就没有 MR**"、"一簇缺陷 → 一个 MR"、"deliver（push + 开 GitLab MR）"、"`src/gitlab/client.ts` — push + 创建 MR"。

**问题**：这是所有 agent 进入仓库时的第一份指令。不改，后续任何 agent（含我）都会按旧目标干活，和新设计直接冲突。

**选项**：
- A. 在实现开始前先单独提交一次 `CLAUDE.md` 重写（项目定位、流水线图、设计约束、关键模块全部按 10-23 更新）
- B. 随第一个实现 PR 一起改

**建议**：A。这是零风险、高杠杆的一步，且应该在任何代码改动之前。

### Q-2 【必须先定】"缺陷单蒸馏"层是否正式进范围

**现状**：见 `J-5`。10-23 §9 差量表没有 `readers/description.ts` / `readers/xlsx.ts`。

**选项**：
- A. 正式进范围，作为 `S1 prefilter` 之前的 `S0.5 distill` 阶段，新增 `pipeline/distill.ts`（模板解析 + 清洗 + `descriptionTooThin` + 模块取值）；Excel 读取放 `readers/xlsx.ts`（过渡期用，接口到位后退役）
- B. 蒸馏逻辑并入 `prefilter.ts`，不单独成阶段
- C. 不做，继续在裸文本上工作

**建议**：A。理由：① 你明确说"主攻缺陷单蒸馏"；② 它是 0 LLM、纯规则、可用两份 xlsx 样本做回归的模块，是整条链里最容易做对的一段；③ 蒸馏产物（结构化 `DefectDigest`）会被 `prefilter`、`aggregate`、`analyze` prompt、报告 `conclusion.observed` 四处消费，单独成模块便于测试与复用。
**附带决策**：蒸馏产物是否写盘为 `clusters/{id}/digest.json`（建议写，便于调试与评测）。

### Q-3 `suggestedAction` 两次判定的归属

**现状**：10-23 §8 写 `S1` 规则初判、`S4` analyze 内模型确认；冲突时谁说了算没写。

**选项**：
- A. 规则优先：`S1` 命中硬规则（CVE / `.dll` / 端侧 / 偶现）时锁定，模型不得改判；未命中时由模型判
- B. 模型优先：规则只做初值注入 prompt，最终以模型为准
- C. 分层：规则命中 `not_code` / `config_or_dependency` 时锁定（这两类不需要看代码即可判）；`code_fix` / `needs_runtime_info` / `needs_design_input` 之间允许模型改判，但改判必须在 `handoff` 写明理由

**建议**：C（默认）。理由：SCA/CVE 类是"常识不是分析"，让模型看代码后再判只会浪费会话且有编造风险；而"是不是需要运行时才能定"确实要看完代码才知道。改判留痕是为了后续评测。

### Q-4 【必须先定】报告 JSON 的物理布局

**现状**：10-23 §4.3 的 run 级 schema 把 `clusters[]` 内联（含 6 段全量）；§4.2 又说 L3 detail "JSON 分文件存放"；`BOUND-1` 提了每簇 `repair-task.json` 但全文没给 schema。

**选项**：
- A. `analysis-report.json` 内联全量 `clusters[]`（简单，但大批次时一个文件很大，违背"防止报告过长"）
- B. `analysis-report.json` 只含 `summary` + `clusters[]` 的 L2 brief（`clusterId / title / confidence / suggestedAction / conclusion.summary / localization.primary / detailPath`）；L3 全量放 `clusters/{id}/analysis.json`；`repair-task.json` 不单独存在，即 `analysis.json` 本身
- C. 同 B，但额外产出 `repair-task.json` 作为"去掉 evidenceCompleteness 等内部字段后的对外子集"

**建议**：B（默认）。理由：三层输出的意义就是让下游按需读；`repair-task.json` 与 L3 detail 内容重叠 >90%，单独维护两份 schema 是负担。如果业务侧明确要一个"只含他们该消费字段"的精简文件，再升级到 C。
**附带**：`analysis-report.md` 的渲染粒度是否也分层（run 级 MD 只渲染 L1+L2，L3 按簇折叠或分文件），建议随 B 一致。

### Q-5 `Defect.attachments` 是否进 v1 schema

**现状**：10-22 `DEC-4` 待决；10-23 的 `evidence.type: "attachment"` 与 `evidenceCompleteness.hasReproduction` 已默认它存在。当前 `types.ts::DefectSchema` 没有该字段。

**选项**：
- A. 进 v1：`attachments: Array<{ path, role: "expected"|"actual"|"extra", kind: "image"|"video"|"file" }>`，可为空数组；`attachmentsUnavailable: boolean` 标记手动导出模式
- B. 不进，全部靠 `evidenceGaps.attachmentsUnavailable = true`

**建议**：A（默认）。理由：10-22 §5.2 已指出后期追加会波及 analyze prompt、artifact、报告三处；现在加成本最低。手动导出模式下传空数组 + `attachmentsUnavailable: true` 即可。

### Q-6 `LOC-R` 铁律（Grep 只允许在 `scopeHint` 内）的执行机制

**现状**：10-22 §7 写"越界搜索必须在 transcript 中说明理由"，是 prompt 约束。

**选项**：
- A. 纯 prompt 约束
- B. 用 Agent SDK 的 `PreToolUse` hook 硬拦截：`Grep` / `Glob` 的 `path` 参数不在 `scopeHint.files ∪ scopeHint.dirs` 内时拒绝并返回"请在 scopeHint 内搜索，或在最终报告的 `handoff.openQuestions` 说明为何需要越界"
- C. 软拦截：允许越界但记录次数，越界次数 > N 触发 `CONF-*` 降级

**建议**：B 为主、C 为兜底（默认）。理由：与 `J-3` 同一原则——可计算的规则比 prompt 可靠。但 `scopeHint` 本身可能为空（无版本 tag、无 `reportedAt`），此时应退化为全仓可搜，不能把 agent 锁死；所以 B 的拦截条件是"`scopeHint` 非空且越界"。

### Q-7 【必须先定】双引擎（`pipeline` / `langgraph`）去留

**现状**：`src/graph/cluster-graph.ts`（590 行）是修复流程的 LangGraph 镜像，节点为 `ensure_repo → analyze → prepare → implement → static_check → verify → classify → review → deliver`。修复段退役后，子图只剩 `ensure_repo → analyze`。`test/integration/langgraph-engine.test.ts` 对两个引擎做逐项比对。

**选项**：
- A. 保留双引擎，`cluster-graph.ts` 重写为 `distill → prefilter → scope_hint → analyze → confidence → render`
- B. 退役 `langgraph` 引擎，只保留 `pipeline`；`@langchain/langgraph` 依赖移除；`docs/langgraph.md` 删除
- C. 保留 `langgraph` 作为唯一引擎，删 `runner.ts` 的命令式实现

**建议**：B。理由：① 双引擎的维护成本是逐项比对测试 + 每个阶段两份实现；② 新流水线前半段（`distill / prefilter / dedupe / scope-hint`）是 0 LLM 纯函数，后半段只有 `analyze` 一次会话，没有修复循环的"条件回边"，StateGraph 的价值（可视化循环、可中断）大幅下降；③ LangGraph Server / Studio 部署需求目前没有业务侧提出。如果未来需要，在新流水线稳定后再加一层薄适配即可，比现在维护两份便宜。
**风险**：若 LangGraph 部署是已承诺的能力，则选 A。这是我不掌握的信息，见 `U-3`。

### Q-8 【必须先定】SWE-bench 适配器与修复侧 skills 去留

**现状**：
- `adapters/swe-bench/`：以产出 `predictions.jsonl`（patch）为目标，依赖 `handlers` 注入 checkout / patch 交付，与"只分析不改码"直接相悖。
- `skills/` 12 个中，修复侧 5 个：`verify-green-gate`、`reproduction-test`、`gitlab-mr-hygiene`、`patch-review`、`minimal-diff`；分析侧有用的：`hierarchical-localization`、`systematic-debugging`、`vue-debug`、`test-triage`；中性：`electron-process-boundary`、`monorepo-workspace`、`typescript-null-safety`。

**选项**：
- A. 全部退役（随包发布的 `skills/` 只保留分析侧 + 中性）
- B. SWE-bench 适配器改造为"分析质量评测"：用 instance 的 `patch` 中涉及的文件集作为 `localization.primary` 的 ground truth，评测定位命中率；skills 修复侧 5 个退役
- C. 原样保留，不碰

**建议**：B。理由：报告型 Agent 最需要的是**定位准确率的客观评测**，SWE-bench 的 gold patch 恰好提供了"真正改了哪些文件"的真值，是现成的评测集；但 patch 产出链路必须砍掉。skills 修复侧 5 个与新边界无关，保留只会让模型在分析时被"最小 diff / GREEN 门禁"的指令干扰。
**注意**：10-23 §3 把 `agent/*` 和 `skills` 列为"保留"，没有细分；本条是对其细化。

### Q-9 `cluster.repoSet`（多仓）是否进 v1 schema

**现状**：10-22 环境适配层 `DEC-20` 待决。只读模式下多仓只影响"去哪几个目录读代码"，不再有联合启动、原子交付问题。

**选项**：
- A. 进 v1，`repoSet: Array<{ repoKey, path, subPath? }>`，单仓时 `repoSet.length === 1`
- B. 不进，保持单 `workDir`

**建议**：A（默认），但语义降到"多个只读根目录"。理由：10-23 附录 A 的示例已经在 `localization.primary.repoKey = "web"` 用上了 `repoKey`；现在统一结构成本低，后加要改报告 schema。

### Q-10 `README.md` 对外叙事与 npm 包名

**现状**：包名 `bugfix-agent`，README 以"修 bug 开 MR"为主叙事。

**选项**：
- A. 包名不变，README 重写叙事
- B. 改名（如 `defect-analysis-agent`），README 重写

**建议**：A（默认）。改名涉及发布、下游引用，收益小。README 必须重写，但可以和 `Q-1` 一起做。

---

## 3. 我不确定、需要补信息的点（`U-*`）

| # | 不确定什么 | 为什么影响实现 | 需要什么信息 |
|---|---|---|---|
| `U-1` | 业务侧 agent 的**实际读取方式**：是读文件系统的 `analysis-report.json`，还是通过 HTTP `GET /v1/runs/:runId` 拉取，还是经由 Dify 转发？ | 决定 `Q-4` 的布局是否需要"单次响应可装下"的约束；决定 L3 分文件时 `detailPath` 是本地路径还是 URL | 业务侧 agent 的接入方式；一次典型批次的簇数 |
| `U-2` | **`EnvironmentProfile.localization` 由谁产出**：10-22 适配层给了 A（人工填）/ B（适配会话）/ C（平台）三种形态，`DEC-21` 待决 | `scopeHint` 的 `LOC-S4`（模块 → 目录）和 `LOC-L2`（术语表）完全依赖它；没有它，定位退化到 `LOC-L1`（i18n）+ `LOC-L5`（结构自述） | 首批项目是否有人能填 `moduleMapping` / `glossary` / `i18n.dirs`；若无，是否接受 v1 先做"自动勘探 i18n 目录 + 路由表"的降级 |
| `U-3` | **LangGraph Server / Studio 部署是否是已承诺的能力** | 决定 `Q-7` 选 A 还是 B | 是否有外部依赖该引擎 |
| `U-4` | **目标仓库是否有版本 tag**（10-22 `DEC-17`，标注"最急"） | `LOC-S1`（tag diff）是 `scopeHint` 四信号里优先级最高的；没有它只剩时间窗 git log + 模块目录 | 首批项目仓库的 tag 规范 |
| `U-5` | **缺陷单的到达形态**：当前是手动导出 Excel；接口"暂缺"。接口何时到位、字段是否与 111 列一致 | 决定 `readers/xlsx.ts` 是过渡期产物还是长期维护；决定 `attachments` 是否真能拿到 | 接口排期与字段契约 |
| `U-6` | **`suggestedAction` 五个标签是否与业务侧工单流程对齐**：`config_or_dependency` 走"依赖/配置流程"、`not_code` "直接关单"——这些下游动作是否真实存在 | 标签是路由，路由目标不存在则标签无意义 | 业务侧确认五个标签各自对应的处理流程 |
| `U-7` | **置信度 `high` 的阈值是否过严**：`CONF-4`（`evidenceGaps` 非空→最多 medium）+ `CONF-6`（`code-inference`→最多 medium）叠加后，无 spec、无截图的批次（即当前样本的常态）可能**一条 high 都出不来** | 若 high 永远为空，`topPriority` 排序退化 | 是否接受"首批报告 high 极少"的现实；或是否要把 `spec_missing` 从 `CONF-4` 的触发集中排除 |
| `U-8` | **模型选择**：10-23 §3 说"可用更便宜的模型"，但 `analyze` 要在 25 turns 内完成定位 + 根因 + 证据链 + 6 段结构化输出 | 影响成本估算与 prompt 设计（更小模型需要更强的结构约束） | 首批是否沿用现有模型配置 |
| `U-9` | **`BGA260060587` 附录 A 示例中的 `scopeHintHit` 三项全 true**，是真实跑出来的还是手写示意 | 若是手写，`scopeHint` 命中率没有实测数据，`LOC-S1..S4` 的效果预期（"数千 → 数百"）未验证 | 是否有在真实仓库上跑过 `scopeHint` 的记录 |

---

## 4. 我的建议（`R-*`）

### R-1 落地顺序（按依赖关系，不按日程）

```
① 契约先行（0 LLM）
   types.ts 新 schema（Defect+attachments / DefectDigest / AnalysisReport / ClusterAnalysis）
   pipeline/confidence.ts（CONF-1..7 纯函数 + 单测）
   CLAUDE.md / README.md 重写（Q-1 / Q-10）
   ↓
② 蒸馏层（0 LLM，可用两份 xlsx 回归）
   pipeline/distill.ts（Q-2）→ pipeline/prefilter.ts → pipeline/dedupe.ts → aggregate.ts 重写
   readers/xlsx.ts（过渡期）
   ↓
③ 定位基础设施（0 LLM）
   pipeline/scope-hint.ts（LOC-S1..S4，依赖 git 只读操作）
   pipeline/repo-map.ts 加 i18n locale 索引 + 路由表索引
   workspace/git.ts 只读化（去 clone / worktree）
   ↓
④ analyze 重写（唯一 LLM 阶段）
   prompt 注入 digest + scopeHint + i18n 线索；声明"无栈 / 附件可能不可读"
   artifacts.ts 换 6 段 schema；fixability → evidenceCompleteness
   LOC-R hook（Q-6）
   ↓
⑤ 渲染
   render/report-json.ts / report-md.ts（Q-4 布局）
   runner.ts 砍到 analyze → confidence → render
   ↓
⑥ 退役
   删修复侧模块与测试；Q-7 / Q-8 执行；package.json 依赖清理
```

**为什么这个顺序**：①②③ 全是 0 LLM 纯函数，可以在没有 API key、没有真实仓库的情况下靠 xlsx 样本和 fixture 仓库把测试做实；④ 是唯一不确定性高的阶段，放在基础设施就位后做，prompt 迭代时输入已经稳定；⑥ 放最后是为了在新链路跑通前旧链路仍可对照。

### R-2 评测先于 prompt 调优

报告型 Agent 的核心指标是**定位准确率**和**置信度校准度**，不是"修复率"。建议在 ④ 之前就建两个评测集：

- **蒸馏回归集**：两份 xlsx 的 60 条 → 期望的 `DefectDigest`（模板段落、模块取值、`descriptionTooThin`、`suggestedAction` 初判）。纯规则，100% 可断言。
- **定位真值集**：10-22 附录 A 的 6 条 hcp Open 样本中，`BGA260060855` 与已 Solved 的 `BGA250766745` 同现象，后者的实际修复文件可作真值；加上 `Q-8` 若选 B，SWE-bench instance 的 gold patch 文件集。指标：`localization.primary.file` 是否在真值集内、`alternatives` 的 recall。

没有这两个集，`CONF-*` 的阈值和 prompt 的改动都无法判断是变好还是变坏。

### R-3 `confidence.ts` 的输入必须是报告对象本身，不能是模型自评

即 `rateConfidence(clusterAnalysis, { repoPath, scopeHint }) → { confidence, triggers: ConfTrigger[] }`。模型可以在 `rootCause.confidenceBasis` 写它的理由，但最终 `confidence` 字段由代码写入，并把触发了哪些 `CONF-*` 记录到 `handoff`（便于下游和评测知道"为什么被压到 medium"）。这是 `J-3` 的落地形式。

### R-4 `scopeHint` 为空时的退化路径要显式

四信号全缺（无 tag、无 `reportedAt`、无 `module` 映射）在首批项目完全可能发生。此时：`LOC-R` 不生效（`Q-6`）、`scopeHintHit` 三项全 false、`CONF-*` 不因此降级（否则所有簇都 low），但报告 `handoff.evidenceGaps` 加 `scope_hint_unavailable`，让下游知道定位是全仓搜索的结果。

### R-5 `S1 prefilter` 的规则阈值放配置、不放代码

CVE / `.dll` / `.exe` / `软件成分分析` / 端侧设备特征 / `偶现` 这些关键词命中规则，业务不同会变。建议走 `EnvironmentProfile.policies` 或 run 级 `options.prefilterRules` 覆盖，代码只提供默认集。对应 10-22 "阈值可在 `business` 覆盖"。

### R-6 保留一个"旧报告兼容"字段，而不是兼容整个旧 schema

现有 `RunReport { fixed[], unfixed[] }` 的消费者是 Dify 工作流。新 `AnalysisReport` 完全不同。建议新报告根部加 `schemaVersion: 2`，`GET /v1/runs/:runId` 的响应用 `schemaVersion` 区分，不做字段级兼容——`fixed[]` 在新语义下本来就不存在，兼容是伪需求。

### R-7 两处文档同步

- 10-23 §9 差量表补 `pipeline/distill.ts` / `readers/xlsx.ts`（若 `Q-2` 选 A）与 `confidence.ts` 的输入输出签名（`R-3`）。
- 10-23 §4.3 / §4.2 的布局矛盾按 `Q-4` 结论改写，并补 `clusters/{id}/analysis.json` 的 schema（即 §4.4 全量）。

---

## 5. 决策汇总表

| # | 决策 | 必须先定 | 默认选项 | 不选默认的触发条件 |
|---|---|---|---|---|
| `Q-1` | `CLAUDE.md` 重写时机 | ✅ | A 先单独提交 | — |
| `Q-2` | 蒸馏层进范围 | ✅ | A 独立 `distill.ts` | 业务侧接口很快到位且字段已结构化 → 可简化为 B |
| `Q-3` | `suggestedAction` 判定归属 | | C 分层 | — |
| `Q-4` | 报告物理布局 | ✅ | B brief 内联 + detail 分文件 | 业务侧要独立精简文件 → C |
| `Q-5` | `attachments` 进 v1 | | A 进 | — |
| `Q-6` | `LOC-R` 执行机制 | | B hook 硬拦截 + C 兜底 | — |
| `Q-7` | 双引擎去留 | ✅ | ~~B 退役 langgraph~~ → **已改判：全量 LangGraph Python + Claude Code**（见跟进文） | — |
| `Q-8` | SWE-bench 与修复侧 skills | ✅ | ~~B 改评测~~ → **已改判：SWE 全删**（见跟进文） | — |
| `Q-9` | `repoSet` 进 v1 | | A 进（只读根目录语义） | — |
| `Q-10` | 包名与 README | | A 不改名、重写 README | — |

> 5 个"必须先定"中，`Q-1`、`Q-2`、`Q-4` 我建议直接按默认执行；`Q-7`、`Q-8` 涉及对外承诺与评测策略，需要你确认。
