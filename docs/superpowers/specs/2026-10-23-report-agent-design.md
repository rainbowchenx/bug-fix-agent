# 报告型分析 Agent 设计（只分析、不出 MR）

> 基线：`main` @ `f018683`（2026-10-23）。
> 前置依据：[缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)（`OBS-*` / `INV-*` / `C-*` / `GAP-F*`）、[目标流水线设计](2026-10-22-target-pipeline-design.md)（`S0..S10` / `CLS-*` / `LOC-*` / `GATE-*` / `DEL-*`）、[环境适配层与能力降级](2026-10-22-environment-adapter-and-capability-degradation.md)（`ENV-*`）。
> 定位：本文**重新划定产品边界**——本产品只产出**分析报告**，不做代码修复；修复由业务侧已有的 spec 开发框架与 agent 承担。本文定义报告契约、置信度规则、交接字段与流程收敛。
> 与既有文档的关系：`target-pipeline-design.md` 的 `S8..S10`（交付/改码/验证执行）**不在本产品范围内**，降级为下游职责；本文为最终边界定义。

---

## 0. 结论先行

| 判断 | 内容 |
|---|---|
| 产品边界 | **只分析、出报告**。改码 / 验证执行 / MR 全部交给业务侧 agent |
| 为什么这样更好 | ① 环境复杂度归位（业务侧天然拥有）；② 我们擅长广度、他们擅长深度；③ 双视角更易发现隐藏问题；④ 报告是可复用资产，MR 是一次性的 |
| 去掉"可修复性判断" | ✅ 不做「能不能修」的结论；改为 `confidence`（高/中/低）+ `suggestedAction`（路由标签） |
| 不筛条 | 所有缺陷都出报告条目；**只排序与路由，不丢弃** |
| 报告 = 产品 | 读者是**业务侧 agent**，因此"机器优先"：结构化 JSON + 人读 MD 双形态 |
| 最值钱的两个字段 | `ruledOut`（已排除假设）+ `openQuestions`（开放问题）——这才是省下游 token 的真正来源 |
| 举证纪律 | `fixability` gate 删除，但保留 **`evidenceCompleteness`** 内部字段作为纪律约束（不是 gate） |
| 流程收敛 | `S0..S6` + `S7'`（产出验证方案，不执行）；`S8..S10` 移出 |

---

## 1. 产品边界重划

### 1.1 为什么不做修复

| # | 理由 |
|---|---|
| 1 | **环境复杂度归位**：业务侧已有 spec 开发框架、私服、规范、双仓启动方式。他们做修复的边际成本远低于我们重新适配 |
| 2 | **能力匹配**：我们擅长**广度扫描**（一次读整批缺陷、跨模块批量定位）；他们擅长**深度确认**（跑起来看、对照规范、看运行时） |
| 3 | **双视角互补**：报告把"候选 + 证据"摆出来，他们的 agent 在**已收敛的候选集**上做二次分析，比单 agent 一遍过更容易发现隐藏问题 |
| 4 | **资产 vs 一次性**：报告可复用于工单 / 知识库 / 评测集 / 同类缺陷检索；MR 是一次性产物 |

### 1.2 边界对照

| 能力 | 本产品 | 业务侧 agent |
|---|---|---|
| 拉取缺陷 + 附件 | ❌ 外部 | ✅ |
| 规则预筛 / 分类 / 分簇 | ✅ | 参考 |
| 范围圈定（`scopeHint`） | ✅ | 参考 |
| 定位（`LOC-L0..L5`） | ✅ **核心** | 复核 + 深挖 |
| 根因分析 | ✅ **核心** | 运行时验证 |
| 验证方案（**设计**） | ✅ | **执行** |
| 推荐修复方案 | ✅ | 决策 + 落地 |
| 改码 / 跑测试 / 起服务 | ❌ | ✅ |
| MR / 关单 | ❌ | ✅ |

> **`BOUND-1`** 本产品的唯一交付物是 `analysis-report.{json,md}`（+ 每簇 `repair-task.json`），**不含任何代码改动**。

### 1.3 分工时序

```
[外部] 拉取 open/new + 附件（role: expected/actual）
   ↓
[本产品] 预筛 → 分类 → 分簇 → 范围圈定 → 定位 → 根因 → 验证方案 → 修复方案
   ↓  analysis-report.json（机器读）+ .md（人读）
[业务侧 agent] 读报告 → 二次分析（带运行时）→ 决策 → 修复 → 验证 → MR → 关单
```

---

## 2. 去掉 fixability gate，改用 confidence + suggestedAction

### 2.1 为什么不再做"能不能修"的判断

技术上自洽：`fixability` gate 原本的作用是"拦住不该进入 `prepare/verify/deliver` 的簇"，而这三段已移出本产品——**gate 没有可 gate 的对象**。

同时，判断"能不能修"是业务侧的决策权（他们知道规范与环境边界），我们越权判断反而有害。

### 2.2 但必须处理 43% 的噪音

实测 60 条真实样本中，约 **43% 属于"不需要代码修复"**（SCA/CVE 6 条、端侧 2 条、偶现 2 条、设计本身合理 2 条等）。

若对它们也产出"根因 + 定位 + 修复方案"：

- 报告近一半内容是**编造的因果链**（"zlib 1.3 的 CVE 根因是版本落后"——这是常识，不是分析）
- 业务 agent 要花 token 先排掉噪音，抵消"省 token"的目标
- 几条荒唐结论会稀释整份报告的可信度

### 2.3 解法：路由标签（不筛条，只路由）

| `suggestedAction` | 含义 | 下游动作 |
|---|---|---|
| `code_fix` | 代码逻辑/样式缺陷，需要改码 | 进修复流程 |
| `config_or_dependency` | 配置、依赖、三方组件问题（含 SCA/CVE） | 走依赖/配置流程，**不烧修复 token** |
| `needs_runtime_info` | 必须运行时信息才能定（偶现、端侧、需实机） | 先补环境/图/日志，再回看报告 |
| `needs_design_input` | 缺 spec / 缺设计稿 / 需求本身待确认 | 找产品或设计确认 |
| `not_code` | 不是代码缺陷（误报、产品决策、限制说明） | 直接关单 |

> **`BOUND-2`** 不丢任何条目；`confidence` + `suggestedAction` 只用于**排序与路由**，不作为 gate。

### 2.4 保留举证纪律：`evidenceCompleteness`

`fixability` 有两重作用：① gate（删掉）；② 逼模型"证据不足就不要编"（**保留**）。

因此内部保留一个不对外输出为结论的字段：

```jsonc
"evidenceCompleteness": {
  "hasReproduction": false,
  "hasCodeEvidence": true,
  "hasSpecOrDesign": false,
  "missing": ["spec", "attachment_video"]
}
```

它驱动 §5 的强制降级，而不产生"可修/不可修"结论。

---

## 3. 职责收敛

| 项 | 处理 | 说明 |
|---|---|---|
| ❌ 删除 | `fixability` gate、`implement`、`verify`（执行）、`static-check`、`baseline`、`scope-lock`（执行）、`review`、`deliver`、`gitlab`、`reproduce`、`dev-server`、MCP 浏览器、多仓交付 | 约现有 `src/` 的 35~40% |
| ✅ 保留 | 预检、规则分类、去重分簇、`scopeHint`、`LOC-L0..L5` 定位、根因、方案、`report`、`store`、`workspace/git`(只读)、`agent/*` | 基础 + 核心 |
| ➕ 新增 | `confidence` 评级器（含强制降级）、`suggestedAction` 路由、`openQuestions`、`ruledOut`、`toUpgradeConfidence`、双形态报告渲染 | 4~6 个模块 |

> 副作用（正面）：只读 Agent **不需要 install / 起服务 / 跑测试** → 业务环境的 8 类异构里有 6 类对本文不成立；可高并发（不抢端口、不装依赖）；可用更便宜的模型。

---

## 4. 报告契约

### 4.1 读者与形态

| 读者 | 形态 | 要求 |
|---|---|---|
| 业务侧 agent | `analysis-report.json` | 机器可解析、字段带 provenance（为什么这么判） |
| 人（开发/测试/产品） | `analysis-report.md` | 按簇折叠，先结论后证据 |
| 单簇交接 | `clusters/{id}/repair-task.json` | 下游 agent 的单次输入 |

### 4.2 三层输出（防止报告过长）

```
L1 summary        1 屏：总量 / 置信度分布 / 动作分布 / Top N 值得先看
L2 cluster brief  每簇 5 行：结论一句话 + 定位文件 + 置信度 + 建议动作
L3 cluster detail 完整 6 段（按需读取，JSON 分文件存放）
```

### 4.3 Run 级 schema

```jsonc
{
  "runId", "projectId", "generatedAt",
  "engine": { "model", "promptVersion", "durationMs", "tokenUsage" },
  "workspace": { "workDir", "baseSha", "repoSet": [], "profileId" },
  "summary": {
    "total": 0,
    "byConfidence": { "high": 0, "medium": 0, "low": 0 },
    "byAction": {
      "code_fix": 0, "config_or_dependency": 0,
      "needs_runtime_info": 0, "needs_design_input": 0, "not_code": 0
    },
    "byClass": { "CLS-1": 0, "CLS-2": 0, "CLS-3": 0, "CLS-4": 0, "CLS-5": 0 },
    "topPriority": ["clusterId", "…"]      // 按 confidence × severity 排序
  },
  "clusters": [ /* 见 4.4 */ ]
}
```

### 4.4 每簇必含 6 段

```jsonc
{
  "clusterId", "defectIds": [], "title",
  "class": "CLS-1",
  "confidence": "high" | "medium" | "low",
  "suggestedAction": "code_fix",

  // ① 完整分析结论
  "conclusion": {
    "summary": "一句话结论",
    "observed": "从缺陷单读到的事实（引原文）",
    "expected": "应有行为",
    "expectedBasis": "spec | design-image | code-inference | user-stated",
    "gap": "事实与应有的差异"
  },

  // ② 根因分析（每条证据必须可核查）
  "rootCause": {
    "oneLine": "…",
    "failureMode": "race_condition | nil_propagation | logic_error | …",
    "chain": [
      { "claim": "…", "evidence": { "type": "code", "file": "…", "line": 42, "snippet": "…" } },
      { "claim": "…", "evidence": { "type": "attachment", "path": "…", "role": "expected" } },
      { "claim": "…", "evidence": { "type": "defect", "field": "缺陷描述.实际结果" } }
    ],
    "confidenceBasis": "为什么给这个置信度"
  },

  // ③ 定位
  "localization": {
    "primary": { "repoKey": "web", "file": "src/…/Report.vue", "symbol": "onReset", "lines": "120-135" },
    "alternatives": [{ "file": "…", "why": "…" }],
    "howFound": "LOC-L1 i18n: '单门店报表' → key report.store.title → 组件",
    "scopeHintHit": { "inVersionDiff": true, "touchedInWindow": true, "inModuleDir": true }
  },

  // ④ 验证方案（设计，不执行）
  "verification": {
    "kind": "unit | component | i18n-key | probe | visual | manual",
    "steps": ["…"],
    "passCriteria": ["…"],
    "whyThisProvesIt": "…"
  },

  // ⑤ 推荐修复方案
  "proposedFix": {
    "summary": "…",
    "steps": [{ "title": "…", "file": "…", "change": "…", "risk": "low" }],
    "targetFiles": [{ "path": "…", "reason": "…" }],
    "acceptance": ["…"],
    "minimalDiffHint": "预计改动 < 10 行 / 单文件"
  },

  // ⑥ 风险 / 缺口 / 交接
  "handoff": {
    "ruledOut": [
      { "hypothesis": "以为是接口返回缺字段", "reason": "api 层字段存在", "evidenceRef": "#2" }
    ],
    "openQuestions": [
      "重置后控件值是否真的为空？需在页面操作后读 DOM 确认"
    ],
    "evidenceGaps": ["spec_missing", "attachment_video_skipped"],
    "toUpgradeConfidence": "若能在页面确认 X，则可升为 high",
    "estimatedEffort": "S | M | L"
  },

  "evidenceCompleteness": { "hasReproduction": false, "hasCodeEvidence": true,
                            "hasSpecOrDesign": false, "missing": ["spec"] }
}
```

---

## 5. 置信度标准与强制降级

### 5.1 评级判据

| 级别 | 判据（全部满足才是 high） | 典型 |
|---|---|---|
| **high** | ① 定位到**文件 + 符号**且文件真实存在；② 因果链每条证据可核查；③ 落在 `scopeHint` 内；④ `evidenceGaps` 为空；⑤ 不依赖运行时信息 | `CLS-4` i18n key 缺失（可静态断言）、`CLS-1` 数值边界错（代码可见） |
| **medium** | 定位到文件但未到符号；或 1 处推断无直接证据；或轻度缺口（缺 spec / 缺局部截图） | `CLS-2` 状态未更新（需确认生命周期） |
| **low** | 只到模块/目录；或多候选并列；或关键证据缺失（缺图/缺日志）；或必须运行时才能定 | `CLS-5` 遮挡（需实机渲染）、偶现类 |

### 5.2 强制降级触发器（`CONF-*`，代码级，不靠模型自评）

| ID | 触发条件 | 结果 |
|---|---|---|
| `CONF-1` | `targetFiles` 中有路径不存在 | 强制 `low` |
| `CONF-2` | 引用文件数 > 3 | 最多 `medium` |
| `CONF-3` | 方案含"重构 / 新增依赖 / 改公共 API"字样 | 最多 `medium` |
| `CONF-4` | `evidenceGaps` 非空 | 最多 `medium` |
| `CONF-5` | `localization.primary` 为空 | 强制 `low` |
| `CONF-6` | `expectedBasis === "code-inference"` | 最多 `medium` |
| `CONF-7` | `suggestedAction !== "code_fix"` | `confidence` 上限 `medium` |

> 设计意图：模型天然倾向都给 `high`。**用可计算的规则压制通胀**，比在 prompt 里求它"客观一点"可靠得多。

---

## 6. 交接字段：省下游 token 的真正来源

业务侧 agent 二次分析最贵的不是"再读一遍代码"，而是**重新试错那些走不通的路径**。三个字段解决它：

| 字段 | 作用 | 价值 |
|---|---|---|
| `ruledOut[]` | 已排除的假设 + 排除理由 + 证据引用 | 下游直接跳过，避免重复探索 |
| `openQuestions[]` | 需要运行时/环境才能确认的**具体问题** | 把双视角协作变成明确分工，而不是两边各猜一遍 |
| `toUpgradeConfidence` | 差什么信息能升到 `high` | 给下游一个"最小补证路径" |

> **`BOUND-3`** 这三个字段是报告的必填项，即使内容为"无"。理由：它们把"报告"从**信息**变成**可执行的交接**。

---

## 7. Token 经济学（诚实账）

| 项 | 单体 agent（修复型） | 报告模式（本设计） |
|---|---|---|
| 本产品探索成本 | 每簇 1 次 analyze（25 turns） | **相同**（不会更省） |
| 本产品修复成本 | 每簇 3~5 次会话（implement/verify 循环） | **归零** |
| 业务侧探索成本 | — | **定向**：读报告 + 精读 2~3 文件 + 跑验证 |
| 重复劳动 | 无（同一 agent） | 靠 `ruledOut` 消除 |
| 总 token | 高（修复循环是大头） | 更低（修复交给已有框架，探索已收敛） |

**结论**：省的不是我们的分析成本，而是 ① 整体省掉修复循环的重复探索；② 业务侧从"从零开始"变成"从候选集开始"。
**前提**：报告必须包含 `ruledOut` 与 `openQuestions`，否则业务侧仍要重走一遍。

---

## 8. 流程收敛后的阶段

```
【外部】拉取 open/new + 附件
   ↓
S0 环境预检（读 profile.capabilities；只读，不需要 install/服务）
S1 规则分类 + 初筛（CLS-1..6 + suggestedAction 初判）
S2 去重 → 分簇 → 优先级
S3 范围圈定 → scopeHint
S4 分析与定位（LOC-L0..L5）→ 结论 / 根因 / 定位
S5 验证方案设计（不执行）
S6 推荐修复方案 + 交接字段（ruledOut / openQuestions）
S7' 置信度评级 + 报告渲染（JSON + MD）
   ↓
analysis-report.{json,md} + clusters/{id}/repair-task.json
```

与 `target-pipeline-design.md` 的映射：

| 原阶段 | 现在 |
|---|---|
| `S0..S6` | 保留（`S0` 改为读 capabilities） |
| `S7` 验证分流（执行） | → **`S5` 验证方案设计（不执行）** |
| `S8` 交付前校验 | 移出（下游职责） |
| `S9` 串行交付 / MR | 移出 |
| `S10` 报告 | → **`S7'` 报告渲染**（形态升级为 JSON + MD） |

> **`S5` 的语义变化很重要**：从"证明它修好了"变成"**告诉下游怎么证明**"。`passCriteria` 要写到下游 agent 能直接执行的程度。

---

## 9. 与现有实现的差量

| 位置 | 改动 |
|---|---|
| `pipeline/analyze.ts` | 注入 `scopeHint` + i18n/术语线索；输出 6 段报告结构；删除 fixability gate 语义 |
| `pipeline/fixability.ts` | **退役**（逻辑改为 `evidenceCompleteness` 采集，见 §2.4） |
| `pipeline/report.ts` | 重写为报告渲染器（L1/L2/L3 三层 + JSON/MD 双形态） |
| `pipeline/aggregate.ts` | 无栈聚合（去重 → 模块分桶 → 文本相似 → 同模块强制合簇） |
| `pipeline/repo-map.ts` | 增加 i18n locale 索引、路由表索引 |
| 新增 `pipeline/prefilter.ts` | `S0`/`S1` 规则预检 + 分类 + `suggestedAction` 初判 |
| 新增 `pipeline/dedupe.ts` | `S2` 去重 |
| 新增 `pipeline/scope-hint.ts` | `S3` 四信号圈定 |
| 新增 `pipeline/confidence.ts` | `CONF-1..7` 强制降级 + 评级 |
| 新增 `render/report-{json,md}.ts` | 双形态渲染 |
| 退役（移出本产品） | `implement.ts`、`verify.ts`、`static-check.ts`、`baseline.ts`、`review.ts`、`scope-lock.ts`、`deliver.ts`、`gitlab/`、`profiles/`、`util/exec.ts` |

---

## 10. 已定决策（本文即结论）

| # | 决策 | 结论 |
|---|---|---|
| `DEC-24` | 是否接受 `suggestedAction` 路由标签 | ✅ 接受；不筛条，只路由/排序（`BOUND-2`） |
| `DEC-25` | 报告形态 | ✅ 双形态：`analysis-report.json`（agent）+ `.md`（人） |
| `DEC-26` | `expectedBasis` 是否必须显式声明 | ✅ 必须；`code-inference` 触发降级（`CONF-6`） |
| `DEC-27` | 置信度级别 | ✅ `high/medium/low` 三档 + `toUpgradeConfidence` 表达"差什么" |
| `DEC-28` | `ruledOut` / `openQuestions` 是否必填 | ✅ 必填，无内容填"无"（`BOUND-3`） |

---

## 11. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 置信度通胀 | 全给 `high` | `CONF-1..7` 代码级强制降级 |
| 43% 噪音 | 报告一半是 CVE/端侧 | `suggestedAction` 路由 + 按 confidence 排序（不丢条） |
| 幻觉定位 | 指向不存在的文件 | 路径存在性校验 → `CONF-1` 强制 low |
| 报告过长 | 业务 agent 读不完 | L1/L2/L3 三层；detail 分文件按需读 |
| 编造因果 | "CVE 根因是版本旧" | `chain[].evidence` 必须可核查；无证据 claim 直接删除 |
| 无 spec 时把现状当正确 | 误判"应有行为" | `expectedBasis` 必填 + `code-inference` 降级（`CONF-6`） |
| 业务侧仍要重走探索 | 报告只给结论不给过程 | `ruledOut` + `openQuestions` 必填（`BOUND-3`） |
| 我们看不到运行时 | 隐藏问题漏掉 | 这正是分工的意义：`openQuestions` 精确指定"请你看这一处" |

---

## 附录 A：单簇报告示例（真实样本 `BGA260060587`）

输入（脱敏后）：

```
标题：[智能巡检_报表] 单门店报表巡检任务报表重置后，导出失败
描述：…操作步骤：1.底部巡检任务展开筛选项，点击重置 2.点击导出
     实际结果：导出失败
     初步定位：重置后时间范围（Scheduled Start Time控件）被清空导致，重新配置时间可导出成功
```

输出：

```jsonc
{
  "clusterId": "c1-…", "defectIds": ["BGA260060587"],
  "title": "单门店报表重置后导出失败",
  "class": "CLS-2", "confidence": "medium", "suggestedAction": "code_fix",

  "conclusion": {
    "summary": "重置动作把时间范围控件值清空，导出逻辑未对空值兜底，导致导出请求参数非法而失败。",
    "observed": "缺陷单明确：重置→导出失败；重新配置时间后导出成功。",
    "expected": "重置应恢复默认时间范围（而非清空），或导出前对空值回退默认区间。",
    "expectedBasis": "user-stated",
    "gap": "重置后状态为「空」，而导出假设「有值」。"
  },
  "rootCause": {
    "oneLine": "重置逻辑清空时间范围，导出前缺少默认值回退。",
    "failureMode": "state_corruption",
    "chain": [
      { "claim": "重置清空 Scheduled Start Time 控件值", "evidence": { "type": "defect", "field": "缺陷描述.初步定位" } },
      { "claim": "导出直接读取该控件值，未做空值兜底", "evidence": { "type": "code", "file": "src/…/ReportFilter.vue", "line": 88, "snippet": "const range = form.scheduledRange;" } },
      { "claim": "空区间导致导出请求参数非法", "evidence": { "type": "code", "file": "src/api/report.ts", "line": 31, "snippet": "params.start = range[0].toISOString();" } }
    ],
    "confidenceBasis": "缺陷单已给出控件级定位；代码链路为静态阅读推断，未经运行时确认 → 故为 medium。"
  },
  "localization": {
    "primary": { "repoKey": "web", "file": "src/…/ReportFilter.vue", "symbol": "handleReset", "lines": "72-90" },
    "alternatives": [{ "file": "src/api/report.ts", "why": "导出参数拼装处同样缺少兜底" }],
    "howFound": "LOC-L1：'Scheduled Start Time' → locale key → 组件；LOC-L0：模块 → 报表目录",
    "scopeHintHit": { "inVersionDiff": true, "touchedInWindow": true, "inModuleDir": true }
  },
  "verification": {
    "kind": "component",
    "steps": [
      "mount ReportFilter，模拟点击重置",
      "断言 scheduledRange 为默认区间而非 undefined/null",
      "触发导出，断言 api 调用参数 start/end 均存在且可序列化"
    ],
    "passCriteria": ["重置后控件为默认值", "导出请求参数完整"],
    "whyThisProvesIt": "直接覆盖缺陷单描述的操作路径与失败点。"
  },
  "proposedFix": {
    "summary": "重置时回填默认时间区间；导出前对空值回退默认。",
    "steps": [
      { "title": "重置回填默认区间", "file": "src/…/ReportFilter.vue", "change": "handleReset 中 scheduledRange = defaultRange()", "risk": "low" },
      { "title": "导出兜底", "file": "src/api/report.ts", "change": "range 为空时使用默认区间", "risk": "low" }
    ],
    "targetFiles": [
      { "path": "src/…/ReportFilter.vue", "reason": "重置逻辑所在" },
      { "path": "src/api/report.ts", "reason": "导出参数拼装，建议二次兜底" }
    ],
    "acceptance": ["重置后立即导出成功", "默认区间与产品定义一致"],
    "minimalDiffHint": "预计 < 15 行 / 2 文件"
  },
  "handoff": {
    "ruledOut": [
      { "hypothesis": "导出接口后端报错", "reason": "重新配置时间后可导出，说明后端正常", "evidenceRef": "#1" }
    ],
    "openQuestions": [
      "重置后控件的实际值是什么（undefined / null / 空数组）？需在页面操作后读 DOM 或打印状态确认"
    ],
    "evidenceGaps": ["spec_missing"],
    "toUpgradeConfidence": "若运行时确认控件值为 null 且导出在此处抛错，可升为 high",
    "estimatedEffort": "S"
  },
  "evidenceCompleteness": { "hasReproduction": false, "hasCodeEvidence": true,
                            "hasSpecOrDesign": false, "missing": ["spec"] }
}
```

## 附录 B：业务侧 agent 的接入约定

| 项 | 约定 |
|---|---|
| 读取入口 | `analysis-report.json` → `summary.topPriority` 决定处理顺序 |
| 跳读建议 | 先读 `clusters[].conclusion.summary` + `suggestedAction`，再按需读 `detail` |
| 必须消费 | `handoff.ruledOut` / `handoff.openQuestions` / `localization.primary` |
| 可直接复用 | `verification.steps` 作为验证脚本骨架；`proposedFix.targetFiles` 作为改动范围初值 |
| 不应信任 | `confidence=low` 的 `rootCause.chain` 细节；`expectedBasis=code-inference` 的"应有行为" |
| 回写（可选） | 每簇实际改动文件 / 验证结果 / 是否采纳 → 用于后续评测与提示词迭代 |
