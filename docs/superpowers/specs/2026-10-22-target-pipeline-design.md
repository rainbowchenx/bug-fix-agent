# 目标流水线设计（缺陷修复主流程）

> 基线：`main` @ `550eb7a`（2026-10-22）。
> 前置依据：[缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)（下称「输入契约」，引用其 `OBS-*` / `INV-*` / `DEC-*` / `C-*` / `GAP-F*` 编号）。
> 定位：本文是**目标流程的固化设计**，回答「一个缺陷从进来到交付，每一步做什么、用什么判、失败怎么收」。**不含实现**；实现任务按 §11 分期拆解。
> 与既有规格的关系：本文不修改 `2026-10-14-local-bugfix-agent-design.md` 的产品定位（全自动无断点 / 一簇一 MR / 没有 GREEN 就没有 MR），只重排**流水线阶段与判定语义**。
>
> **前置阶段**：几条业务环境异构（自定规则、外部定位平台、无单测、前后端双仓）的应对方案——前置 `EnvironmentProfile` 适配层与 `L0..L3` 能力降级——见 [环境适配层与能力降级](2026-10-22-environment-adapter-and-capability-degradation.md)。本文的 `S0` 应改为「读 `profile.capabilities`」。
>
> **⚠️ 产品边界变更（以本文为准之前请先读）**：本产品最终**只产出分析报告，不执行修复**。因此本文的 `S7`（验证执行）、`S8`（交付前校验）、`S9`（串行交付 / MR）已**移出本产品范围**，降级为下游职责；`S7` 相应改为「设计验证方案」。最终边界与报告契约见 [报告型分析 Agent 设计](2026-10-23-report-agent-design.md)。

---

## 0. 结论先行

| 判断 | 内容 |
|---|---|
| 原流程主体 | ✅ 成立（输入 → 初筛 → 分簇并发 → analyze → 根因 → 方案 → 验证 → MR） |
| 最大设计缺陷 | ① 分类未绑定动作；② 定位仍假设「能 grep」 |
| 核心改造 | **先圈范围再定位**（新增 `scopeHint` 阶段）+ **分类变成分流器**（决定定位/验证/交付） |
| 不可妥协原则 | 硬门禁（GREEN）只对**能产生客观信号**的类型成立；UI 类一律 Draft |
| 复用率 | 约 65~70%（20+ 模块可直接复用） |
| 落地顺序 | P0 主链路 → P1 UI 验证 → P2 并发 → P3 多仓适配（**并发不产生新价值，只是吞吐**） |
| 环境异构 | 不在核心硬适配，而用前置 `EnvironmentProfile` + `capabilities` 降级（见环境适配层文档） |

---

## 1. 范围边界

### 1.1 Agent 内（本文覆盖）

```
筛选 → 分类 → 分簇 → 范围圈定 → 定位 → 根因 → 改码 → 验证 → 交付 → 报告
```

> **边界修正**：最终产品边界把「改码 → 验证执行 → 交付」移出，本产品止于「定位 → 根因 → 验证方案 → 修复方案 → 报告」。详见 [报告型分析 Agent 设计](2026-10-23-report-agent-design.md)。
> 本文保留完整流程描述，是因为它是**业务侧修复 agent 的参考流程**（我们的报告即为它的输入）。

### 1.2 Agent 外（明确不做）

| 项 | 归属 | 说明 |
|---|---|---|
| 按用户身份 + 项目编号拉取 open/new | 上游工作流 | 见 `INV-5` |
| 附件下载 | 上游工作流 | Agent 只消费已落地的路径 |
| 附件角色标注（expected / actual） | 上游工作流 | Agent 做校验，不做判定（见 `DEC-13`） |
| MR merge 后关闭缺陷单 | 上游工作流 | 涉及写权限与审计；Agent 只提供回写字段 |
| 自动 merge | 不做 | 沿用既有约束 |

> **`INV-5`** Agent 不持有缺陷平台凭据，不做任何缺陷平台写操作；只消费 request 中的 `defects[]` 与附件引用。

---

## 2. 输入契约

```ts
interface RunRequest {
  workDir: string;              // 已是 git 仓，且可本地运行（C-1）
  projectId: string;            // 批次标识；同时作为 repoMapping 的 key
  repoMapping?: {               // monorepo 适配
    [module: string]: { repoUrl: string; subPath?: string; branch?: string };
  };
  business: {
    verify: string[];           // install / test 命令，覆盖探测结果
    specPaths?: string[];       // 设计文档路径，按模块旁挂亦可
    glossary?: Record<string, string[]>;   // 领域术语 → 代码符号/目录（见 LOC-L2）
    devServer?: { command: string; port: number; readyPath?: string };
    uiVerify?: {
      baseUrl: string;
      viewport: { width: 1440; height: 900; deviceScaleFactor: 1; zoom: 100 };
      login?: { url: string; username: string; password: string; selectors?: object };
    };
    concurrency?: number;       // 默认 3
    maxIterate?: { logic?: 3; ui?: 2 };
  };
  defects: Array<{
    id: string;
    title: string;
    description: string;        // 见输入契约 §3 模板解析
    module?: string;            // 优先：标题[]前缀 > 测试模块 > 所属模块（INV-2）
    severity?: string;
    occurrences?: number;       // 频次；缺省由簇大小派生
    reportedAt?: string;        // 申请时间，用于 git log 时间窗（LOC-S2）
    productVersion?: string;    // 版本，用于 tag diff（LOC-S1）
    attachments: Array<{
      path: string;             // 绝对路径，置于 workDir 之外（DEC-12）
      role: "expected" | "actual" | "extra";
      region?: { x: number; y: number; w: number; h: number };  // UI 局部比对区（DEC-18）
      designVersion?: string;   // 设计稿对应版本，用于批次内校验
    }>;
  }>;
}
```

### 2.1 三个必须由上游保证的点

| 点 | 失败后果 |
|---|---|
| `attachments[].role` 标注准确 | UI 类会把错误效果当验收标准 → 修歪 |
| 附件路径在 `workDir` **之外** | `deliverFix` 用 `git add -A`，截图会被提交进 MR |
| `repoMapping` 覆盖所有 `module` | 无法确定落哪个仓/子目录 → 只能 `unfixed` |

---

## 3. 总流程

```
【外】拉取顶点+附件 → request
   ↓
┌─ 阶段 A：准备（0 LLM） ────────────────────────────────────────┐
│ S0 环境预检（fail fast）                                       │
│ S1 规则分类 + 初筛（CLS-1..6，两种淘汰语义）                    │
│ S2 去重 → 粗簇 → 簇大小定优先级                                 │
│ S3 范围圈定 → scopeHint（LOC-S1..S4）                          │
└────────────────────────────────────────────────────────────────┘
   ↓ 并发闸门 3 · 每簇 worktree · install 复用 · 端口分配
┌─ 阶段 B：修复（每簇一条串行会话链） ───────────────────────────┐
│ S4 analyze：类型确认 + 可修复性 + verifiability + 定位/根因/方案 │
│ S5 失败测试 RED（仅客观可验类）                                 │
│ S6 改码（scope lock，预算按类型）                               │
│ S7 验证分流（GATE-* 矩阵）                                      │
└────────────────────────────────────────────────────────────────┘
   ↓
┌─ 阶段 C：交付（串行） ─────────────────────────────────────────┐
│ S8 交付前校验（DEL-1）                                          │
│ S9 串行交付：重叠分组 → rebase → 重验 → MR（DEL-2/DEL-3）       │
└────────────────────────────────────────────────────────────────┘
   ↓
S10 report.json（fixed/unfixed + 类型 + reasonCode + 证据链）
   ↓
【外】merge 后关单
```

---

## 4. 阶段 A：准备（0 LLM）

### S0 环境预检（fail fast）

| 检查 | 不通过时 |
|---|---|
| `workDir` 是 git 仓、有 `.git` | 整批拒绝 |
| 每个缺陷的 `module` 能被 `repoMapping` 命中 | 该缺陷 `unfixed / needs_more_context` |
| `business.verify.test` 可解析（或可探测） | 整批拒绝（无 GREEN 门禁无意义） |
| 附件路径存在且可读 | 该缺陷 `unfixed` |
| UI 类且缺 `role=expected` | 该缺陷 `unfixed`（**不进入后续**，省一整轮会话） |
| UI 类且缺 `business.uiVerify` / `devServer` | 该缺陷降级为 `regression_only` 或 `unfixed` |

> 设计意图：所有**结构性缺料**在 0 LLM 阶段判定完，避免"每簇跑到 analyze 才发现环境不对"。

### S1 规则分类 + 初筛

分类见 §5（`CLS-1..6`）。**淘汰语义必须分两档**：

| 语义 | `reasonCode` | 是否可闭环 |
|---|---|---|
| 信息不足，可退回补 | `needs_more_context` | ✅ 测试补图/补步骤后可重跑 |
| 结构上不该修 | `not_actionable` | ❌ 永久放弃 |

判据（全部可计算，阈值可在 `business` 覆盖）：

| 判据 | 命中 |
|---|---|
| `description === title` 或长度 < 40，且无 `expected` 附件 | 信息不足 |
| 模板段落（实际结果/预期结果/操作步骤）0 命中 | 信息不足 |
| 命中 SCA 特征（`CVE-` / `.dll` / `.exe` / `软件成分分析`） | 不该修 |
| 端侧/设备特征（`Android` / `iOS` / `固件` / 设备型号）无对应仓 | 不该修 |
| 偶现特征（`偶现` / `未复现` / `必现` 缺失） | 不该修（或降级） |
| `当前状态` 含 `3、`（已被真人认领） | 按 `DEC-3`（默认排除） |

### S2 去重 → 粗簇 → 优先级

```
① 去重：标题+描述归一化全等 → 合并（实测 hcp 有 3 条同源 WebScan）
② 粗簇：module 分桶（INV-2 优先级）+ 中文 token 相似度
③ 同模块强制合并（避免同文件多 MR），受上限约束
④ 优先级 = f(簇大小, severity, 是否 UI 可验证)
```

> **顺序修正**：原流程是「先筛选再分簇」。改为**先簇后筛**——簇大小是唯一的"频次"来源（导出表无频次字段），先筛会丢掉这个信号。

### S3 范围圈定 → `scopeHint`（本文最关键的降噪手段）

```
scopeHint = {
  files:   string[],   // 候选文件（从版本 diff 得出）
  dirs:    string[],   // 候选目录（从模块路径得出）
  commits: string[],   // 候选 commit（从申请时间窗得出）
}
```

四个信号（详见附录 A）：

| ID | 信号 | 依赖 | 优先级 |
|---|---|---|---|
| `LOC-S1` | 版本 tag diff → 本版本改动文件集 | 仓库有版本 tag（`DEC-17`） | 最高 |
| `LOC-S2` | `申请时间 - 7d` 窗口内该模块目录的 `git log` | `reportedAt`（实测 30/30 有） | 高 |
| `LOC-S3` | `引入活动 = 编码` → 优先看新增/修改行 | 实测 17/30 | 中 |
| `LOC-S4` | 模块路径 → 目录（`HikCentral Professional/WEB/智能巡检` 三层可直接映射） | `module` | 基础 |

**效果预期**：把"全仓盲搜"压到"版本改动集 × 模块目录"量级（数量级：数千 → 数百）。这是无栈条件下能否定位的决定因素。

---

## 5. 缺陷分类（`CLS-*`）

### 5.1 五类 + 一桶

| ID | 类型 | 典型（真实样本） | 为什么独立 |
|---|---|---|---|
| `CLS-1` | 数值/格式化 | 小数点保留、计算错误 | 缺陷常在**公共 utils**，修一处影响 N 处，回归面要放大 |
| `CLS-2` | 交互/状态 | `重置未区分任务模式`、`tab 切换后勾选无效`、`返回界面非对应待办` | 定位靠组件状态机 + 路由；验证靠状态断言 |
| `CLS-3` | 接口/契约 | `缺少对响应报文状态码的解析`、`接口比基线多` | 锚点是接口名/字段名；验证需 mock |
| `CLS-4` | i18n/文案 | `库名称重复，仅中文翻译`、`选项文字错误` | **不是布局也不是逻辑**；验证可做到 100% 客观（key 齐全性） |
| `CLS-5` | UI 布局/几何 | `字符叠加配置项距离过近`、`150% 缩放下弹窗被遮挡`、`Reselect 被遮挡` | 验证只能目视；门禁天然偏软 |
| `CLS-6` | 不可修桶 | SCA/CVE、端侧、偶现、设计本身不合理 | 必须在建 worktree 前剔除 |

> 补充：UI 类内部还需再分 **静态视觉**（截图可比）与 **交互反馈**（时序，静态截图不够）。后者默认降级为人工确认。

### 5.2 分类时机：三阶段，越早越便宜

| 时机 | 判据 | 作用 | 成本 |
|---|---|---|---|
| **S1（分簇前）** | 纯规则 | 剔除 `CLS-6`、缺料类 | 0 |
| **S4（analyze 内）** | 看代码后确认 | 确认 `CLS-1..5` + `verifiability` | 1 轮会话 |
| **S7（验证后）** | 验证结果 | 允许**重分类**（以为 UI，实为数据未传） | 增量 |

> 现状缺口：`GAP-F5`（一次性判定，无回炉）在此被显式要求修正——S7 允许回退重判一次。

### 5.3 分类必须绑定三个动作（否则分类是负担）

见 §6 矩阵：**定位策略 / 验证手段 / 交付形态**。

---

## 6. 分类 × 定位 × 验证 × 交付 矩阵（`GATE-*`）

| 类型 | 定位锚点 | 验证手段 | 门禁强度 | 交付 |
|---|---|---|---|---|
| `CLS-1` 数值/格式化 | 公共 `utils/format`/计算层（**不是调用点**） | 单测（边界值）+ **放大回归**（同模块全部用例） | 🟢 硬 | 正常 MR |
| `CLS-2` 交互/状态 | 路由表 → 组件 → 状态机 | 单测/组件测（跳转、状态、事件） | 🟢 硬 | 正常 MR |
| `CLS-3` 接口/契约 | 接口名/字段名 → api 层 | mock 单测（请求/响应契约） | 🟢 硬 | 正常 MR |
| `CLS-4` i18n/文案 | 中文文案 → locale JSON → key → 组件 | **key 齐全性断言**（最客观） | 🟢 硬 | 正常 MR |
| `CLS-5` UI 视觉 | 模块目录 → 组件样式层 | Playwright 截图 + `expected` 目视比对（含 `region`） | 🟡 软 | **Draft MR** |
| `CLS-5b` UI 交互反馈 | 同 `CLS-2` | 时序/录制（现状不具备） | 🟡 软 | Draft / 人工 |
| `CLS-6` 不可修 | — | — | — | `unfixed` + 完整说明 |

### 6.1 门禁强度原则（唯一不可妥协项）

> **`GATE-1`** 硬门禁（必须 RED→GREEN 才能开正常 MR）只对 `CLS-1..4` 成立。
> **`GATE-2`** `CLS-5` 的 GREEN 是**模型目视认定**，属软门禁 → 一律 Draft MR + 报告标注"UI 目视通过，需人工确认"。
> **`GATE-3`** 不产生任何客观信号的缺陷（`CLS-6`、`CLS-5b`）不得进入交付。

---

## 7. 阶段 B：修复

### S4 analyze

单会话产出三件套（沿用既有 artifact）：`RootCauseArtifact` + `SolutionArtifact` + `LocalizationArtifact`；新增两个维度：

```ts
{
  class: "CLS-1" | ... | "CLS-5";
  verifiability: "reproducible" | "ui_verified" | "regression_only" | "unverifiable";
}
```

**定位阶梯（`LOC-L0..L5`）——先读地图，再定向搜索**：

| 级别 | 手段 | 说明 |
|---|---|---|
| `LOC-L0` | 已知模块 → 目录 | `module` 三层路径可直接当目录 |
| `LOC-L1` | UI 文案 → locale → key → 组件 | 最可靠；实测锚点：`Scheduled Start Time`、`Create Issue`、`Reselect` |
| `LOC-L2` | 领域术语表 → 代码符号/目录 | `字符叠加`→`OSD`、`抓拍`→`capture`、`巡检`→`inspection`（`business.glossary`） |
| `LOC-L3` | 路由/页面 → 路由表 → 组件树 | 交互/状态类主力 |
| `LOC-L4` | 接口名/字段名 → api 层 | 契约类主力 |
| `LOC-L5` | 仓库结构自述 → 规划搜索 | **禁止无条件全仓 Grep**；必须在 `scopeHint` 内 |

> **`LOC-R`（铁律）**：`Grep` 只允许在 `scopeHint.files ∪ scopeHint.dirs` 范围内执行；越界搜索必须在 transcript 中说明理由。

**现状缺口**：`repo-map.ts` 只扫 80 个文件 + 40 个文件的 export 符号，不索引 i18n、不索引路由、无术语表 → `GAP-L1`、`GAP-L2`。

### S5 失败测试（RED）

- 适用：`CLS-1..4`
- 必须对照 baseline 判定"是新增失败"（`isNewFailure`），避免把既有红当复现
- 产出 `verifyLevel = reproduced`
- 写不出 RED → 降级 `regression_only`（并说明原因）

> **顺序铁律**：RED 必须在改码**之前**。改完再补测试会让测试迎合实现，红→绿证据链失效。

### S6 改码

- 复用 `implementCluster` + `checkScopeLock`
- 迭代预算按类型：`CLS-1..4` = 3 轮，`CLS-5` = **2 轮**（每轮含起服务+截图，成本高；"差一点点"应早停转 Draft）

### S7 验证分流

| 类型 | 验证实现 |
|---|---|
| `CLS-1..3` | 静态检查 + 测试 → exit code |
| `CLS-4` | key 齐全性断言（脚本级，不依赖模型） |
| `CLS-5` | 编排侧起 devServer（端口分配）→ Playwright navigate/login → 截图（含 `region`）→ 与 `expected` 目视比对 → `UI_VERIFY{passed, notes}` |

**UI 验证的三个前提**（现状全缺，`GAP-U1..U3`）：

| ID | 前提 | 现状 |
|---|---|---|
| `GAP-U1` | devServer 生命周期（起 → 就绪 → 停） | 🔴 `IMPLEMENT_TOOLS` 无 `Bash`，`timedExec` 无法长驻 → **必须编排侧托管** |
| `GAP-U2` | 视口归一化（`1440×900 / dpr=1 / zoom=100%`） | 🔴 无约定（`DEC-14`） |
| `GAP-U3` | 凭据注入与防泄漏（交付前扫 diff） | 🔴 无（`DEC-15`） |

---

## 8. 阶段 C：交付

### S8 交付前校验（`DEL-1`）

| 检查 | 不通过 |
|---|---|
| scope lock 复检（改动文件 ⊆ `target_files`） | `implement_failed` |
| **凭据/密钥扫描**（diff 中不得出现登录信息明文） | 拒绝交付，`push_failed` |
| **附件/截图未入 diff**（`git add -A` 风险） | 拒绝交付 |
| 相对 base 无改动 | `no_changes` |

### S9 串行交付（`DEL-2` / `DEL-3`）

> **`DEL-2`** 按「预期改动文件集重叠度」分组，重叠簇**串行**；不重叠可并行。
> **`DEL-3`** 每次交付前 `rebase` 到最新 target，**rebase 后必须重跑验证**（含 UI 重截），否则 GREEN 失效。

为什么必须这样：各 worktree 从同一 `baseSha` 出发推独立分支，**push 时不冲突，冲突发生在 merge 期**。不串行化 = N 个 MR 同时飞、人工解冲突。

### S10 报告

```jsonc
{
  "summary": { "total": 0, "fixed": 0, "unfixed": 0, "byClass": {} },
  "fixed":   [{ "clusterId", "defectIds", "class", "mrUrl", "draft",
                "verify": { "level", "command", "evidence" },
                "scopeHint": { "hit": "files|dirs|commits", "size": 0 },
                "iterations" }],
  "unfixed": [{ "clusterId", "defectIds", "class", "reasonCode", "reasonDetail",
                "evidenceGaps": ["attachment", "repro_env", "spec"] }],
  "writeback": [{ "defectId", "mrUrl", "verifyLevel", "howToVerify" }]
}
```

- `writeback` 是给上游关单用的最小字段集（Agent 不做关单）
- `evidenceGaps` 让上游知道"补什么能重跑"（可闭环 vs 永久放弃）
- 报告是主交付物：**约 43% 缺陷修不了，价值全在这里**

---

## 9. 与现有实现的差量

### 9.1 可直接复用（无改动）

`implement.ts`（含 reproduce phase）、`scope-lock.ts`、`review.ts`、`static-check.ts`、`verify-classify.ts`、`baseline.ts`、`log-snip.ts`、`known-issues.ts`、`report.ts`、`gitlab/client.ts`、`skills/*`（11 个）

### 9.2 需改语义

| 位置 | 改动 | 关联 |
|---|---|---|
| `pipeline/aggregate.ts` | 无栈聚合：去重 → 模块分桶 → 文本相似 → 同模块强制合簇 | `INV-1`/`INV-2`、`S2` |
| `pipeline/analyze.ts` | 注入 `scopeHint` + i18n/术语线索；+`class`/`verifiability`；声明证据缺口 | `GAP-F2`/`GAP-L1`/`S4` |
| `pipeline/repo-map.ts` | 增加 i18n locale 索引、路由表索引 | `GAP-L1` |
| `pipeline/deliver.ts` | 交付前扫 diff；串行 + rebase + 重验；UI 类 Draft | `DEL-1/2/3` |
| `workspace/git.ts` | `workDir` 已是仓 → 仓内 worktree，不 clone；`removeWorktree` 落地；仓级 git 互斥 | `C-1`、`GAP-W3/W4` |
| `runs/store.ts` | `updateRunMeta` 串行化；`writeJson` 原子写 | `GAP-W1/W2` |
| `types.ts` | `repoUrl` 可选；`attachments[].role/region`；`class`/`verifiability`；`verifyLevel += ui_verified` | `C-2` |
| `graph/cluster-graph.ts` | 新增 `ui_verify` 节点；补 `implementNode`/`reviewNode` 漏传 `mcpServers` | 既有 bug |
| `agent/sdk-runner.ts` | `mode: "ui-verify"`；MCP 工具名并入 `allowedTools`（已确认可放开） | `GAP-U1` |
| `profiles/detect.ts` | `resolveWorkspaceCwd` 返回值落地 | `DEC-8` |

### 9.3 需新增

| 模块 | 职责 |
|---|---|
| `pipeline/prefilter.ts` | `S0`/`S1` 规则预检与分类 |
| `pipeline/scope-hint.ts` | `S3` 四信号圈定 |
| `pipeline/dedupe.ts` | `S2` 去重 |
| `pipeline/ui-verify.ts` | `S7` UI 验证会话 + verdict 解析 |
| `workspace/dev-server.ts` | devServer 托管 + 端口分配 + 进程树回收 |
| `scheduler/concurrency.ts` | 并发闸门 + 进度串行写 |
| `readers/xlsx.ts` / `description.ts` | 导出态输入解析（过渡期用） |

---

## 10. 并发基础设施（`GAP-W1..W6`）

| ID | 问题 | 现状证据 | 修法 |
|---|---|---|---|
| `GAP-W1` | `updateRunMeta` 读-改-写竞态 | `runs/store.ts` | 串行写队列或每簇独立 progress |
| `GAP-W2` | `writeJson` 非原子 | `runs/store.ts` | 临时文件 + rename |
| `GAP-W3` | 共享 `.git` 仓级操作抢锁 | `workspace/git.ts` | 进程内互斥 |
| `GAP-W4` | worktree 不回收 | `removeWorktree` 定义但从不调用 | 簇结束 `finally` 清理（失败保留） |
| `GAP-W5` | 每 worktree 独立 install | `prepare.ts` | 每仓一次 install（monorepo 根复用） |
| `GAP-W6` | devServer 端口冲突 | 无 | `basePort + clusterIdx` |

参考现状：`options.concurrency`（`types.ts`）与 `BUGFIX_DEFAULT_CONCURRENCY`（`config.ts`）**均已声明但零使用**。

---

## 11. 落地分期

| 阶段 | 范围 | 目的 | 交付物 |
|---|---|---|---|
| **P0** | 单簇串行 · `CLS-1..4` · 规则初筛 · **范围圈定** · RED→改码→GREEN · 报告 | 证明主链路可信 | `prefilter`、`scope-hint`、i18n 索引、report 扩展 |
| **P1** | `CLS-5` + devServer 托管 + Playwright 目视 → Draft MR | 可修率 43% → ~70% | `dev-server`、`ui-verify`、MCP 打通 |
| **P2** | 并发 3 + `GAP-W1..W6` + 交付串行化/rebase 重验 | 吞吐 | 调度器、并发安全 |
| **P3** | monorepo mapping、`businessConfig` 收敛、术语表 | 多仓适配 | `repoMapping`、glossary |

> 分期依据：**并发不产生新价值，只是吞吐**；`scope-hint` 与 UI 验证才决定可修率天花板。

---

## 12. 待决策项

| # | 决策 | 影响 |
|---|---|---|
| `DEC-12` | 附件落地位置（建议 `workDir` 之外） | MR 干净度 |
| `DEC-13` | expected/actual 由上游标注 vs Agent 猜 | UI 类成败 |
| `DEC-14` | 视口约定 `1440×900 / dpr=1 / zoom=100%` | UI 偏移判定是否成立 |
| `DEC-15` | 凭据注入方式 + 交付前 diff 扫描是否强制 | 泄密风险 |
| `DEC-16` | devServer 归属（建议编排侧托管） | `GAP-U1` |
| `DEC-17` | **仓库是否有版本 tag** | 决定 `LOC-S1` 能否落地——**最急** |
| `DEC-18` | `expected` 截图是否带 `region` / 设计版本 | UI 误判率 |
| `DEC-19` | 交付串行化粒度（全串行 vs 仅重叠串行） | 吞吐 vs 冲突率 |

---

## 13. 风险与边界（不隐藏）

| 风险 | 表现 | 缓解 |
|---|---|---|
| 设计稿过期 | 把正确实现判成 bug，越改越错 | `expected.designVersion` + 报告声明依据版本 |
| 动态内容干扰 | 列表数据/时间戳导致截图天然不一致 | `region` 局部比对 + prompt 约束"只看布局" |
| 偶现缺陷 | 无法稳定复现 | `S1` 直接归 `CLS-6`，不进流水线 |
| UI 软门禁 | "模型说看起来对了"≠"人确认过" | 一律 Draft（`GATE-2`） |
| 公共 utils 修改 | 修一处影响 N 处 | `CLS-1` 强制放大回归范围 |
| 一单多问题 | `BGA260059805` 含 i18n + 遮挡两个问题 | `S4` 输出问题项列表，逐项标注状态 |
| 视频线索缺失 | 约 50% Open 缺陷 `见附件视频` | `evidenceGaps.videoSkipped` 显式标注，不假装看过 |

---

## 附录 A：定位信号实测

| 信号 | 实测证据 | 可得性 |
|---|---|---|
| 版本 | `V5.5.0`（配套 30/30）、`V200R324C001`（hcp 30/30） | ✅ 稳定 |
| 申请时间 | 30/30 有值 | ✅ 稳定 |
| 引入活动 = 编码 | 配套 17/30 | ✅ 部分 |
| 模块三层路径 | hcp 14/30（`HikCentral Professional/WEB/智能巡检`） | ✅ 部分（hcp 型） |
| UI 英文字面量 | `Scheduled Start Time`、`Create Issue`、`Reselect` | ✅ 部分 |
| 堆栈 / 页面 URL | 永远没有（`OBS-6`） | ❌ |

## 附录 B：与原流程的 8 处差异

| # | 原流程 | 本设计 | 原因 |
|---|---|---|---|
| 1 | 先筛选再分簇 | **先分簇再筛选** | 簇大小是唯一频次来源 |
| 2 | 无范围圈定 | **S3 `scopeHint`** | 无栈条件下定位成败的关键 |
| 3 | 逻辑/UI 二分 | **`CLS-1..6`** + 绑定定位/验证/交付 | 交互、契约、i18n、数值路径各不相同 |
| 4 | 按 `MAX_CLUSTER_SIZE` 切片 | **同模块强制合簇** + analyze 后按改动文件集二次合并 | 避免同文件多 MR 必冲突 |
| 5 | 回归验证在改码后 | **RED 在改码之前** | 保红→绿证据链 |
| 6 | 多 worktree 冲突解决 | **串行化 + rebase + 重验** | 冲突在 merge 期不在 push 期 |
| 7 | 无交付前校验 | **`DEL-1`** 凭据/附件扫描 | `git add -A` 会带上截图与密码 |
| 8 | 止于提 MR + 关单 | **显式 `report.json` + `writeback`** | 双结局报告是主交付物 |

## 附录 C：术语表（`LOC-L2`）设计

`business.glossary` 结构：

```jsonc
{
  "字符叠加": ["OSD", "overlay", "text-overlay"],
  "抓拍":     ["snapshot", "capture"],
  "巡检":     ["inspection"],
  "快速配置": ["quick-config", "quickSetup"],
  "视频电警": ["traffic-enforcement", "e-police"]
}
```

用途：把测试人员的**业务词汇**映射到**代码符号 / 目录名**，作为 `LOC-L2` 的检索扩展词。缺失该项时，模型只能靠字面命中和猜测，是当前定位失败的主因之一。

来源建议：由上游按项目维护（属 `business` 输入），或首次运行时从 `module` 列表与仓库目录名自动对齐后人工确认。
