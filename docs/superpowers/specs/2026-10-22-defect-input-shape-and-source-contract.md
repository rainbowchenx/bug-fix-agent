# 缺陷输入形态与来源契约（分析固化）

> 基线：`main` @ `83c568c`（2026-10-22）。  
> 样本：`缺陷列表demo/配套-交通项目.xlsx`、`缺陷列表demo/hcp巡检.xlsx`（各 30 行 × 111 列，表头逐字一致）。  
> 方法：用 `openpyxl` 全量读取两份 xlsx，逐列统计填充率、枚举分布、字段交叉关系、描述模板段落、重复度、附件引用率；对聚类策略做三组对照模拟。  
> 定位：本文固化「缺陷长什么样 / 目标流程对输入的要求 / 与现有实现的契约冲突」，**不是功能规格，也不含实现**。后续规格与计划应引用本文编号（`OBS-*` / `INV-*` / `DEC-*`）。
>
> 输入侧两条业务共识（本文件的立论基础）：
> 1. **所有缺陷单都不会带报错堆栈或代码说明**。来源是测试人员测试过程中发现的文本描述，部分配图片，极少量配视频（视频不处理）。
> 2. 生产上**只导出 `缺陷状态 ∈ {Open, New}`**（即未解决）的单子，其余不处理。当前两份 xlsx 是随机样本，**不代表真实输入分布**。

---

## 0. 结论先行

| 维度 | 结论 |
|---|---|
| 表结构 | 两份样本**表头 100% 相同**（111 列），一个解析器可覆盖，别名表只需处理历史变体 |
| 真实输入规模 | 按 `Open/New` 过滤后：`配套` **1 条**、`hcp` **6 条**；单项目单日约 **6~7 条** |
| 信息密度 | A 档稳定字段 13 个、B 档不稳定字段 8 个、C 档**永远缺失**（堆栈/页面 URL/代码路径/附件内容） |
| 现有聚合规则 | 两条路径（标题指纹 / 栈顶文件并簇）**在无栈数据上全部失效**；30 条 → 30 簇 |
| 现有验证能力 | 无栈 + 多为 UI/文案/偶现 → 真实 7 条里仅 **3 条（43%）可写失败测试** |
| 最大幻觉风险 | 50% 的 Open 缺陷引用附件（`见下图`/`见附件视频`），而导出无附件；**当前 prompt 未声明此缺失** |
| 与目标流程的硬冲突 | 3 处：`workDir` 语义、`repoUrl` 层级、缺"用户身份"维度 |
| 可修复性判定 | **完全由模型自评三态**（`fixability.assessment`）决定，代码仅做枚举映射；无规则预筛、无「可修但不可验证」档位 |

**一句话**：这批数据把产品边界压窄为「**能写失败测试的前端逻辑缺陷修复器**」，而不是通用 bug 修复 Agent；设计必须围绕"无栈 + 仅文本/图 + 单仓单版本"重做定位与验证语义。

---

## 1. 样本事实（`OBS-*`）

### 1.1 文件级

| 项 | 配套-交通项目 | hcp巡检 |
|---|---|---|
| Sheet / 行 / 列 | Sheet1 / 30 / 111 | Sheet1 / 30 / 111 |
| 表头 | 逐字相同（非空列 59 / 58） | 同左 |
| 项目编号 | `PJ01PR20250701315`（30/30） | `PJ14PD20250909046`（30/30） |
| 项目名称 | 交通相机WEB升级项目 | HikCentral Professional 巡检v2.2 |
| 产品 / 版本 | 卡口抓拍摄像机 / `V5.5.0` | HikCentral Professional / `V200R324C001` |
| 产品系列 | 高清抓拍机 | HikCentral Professional |
| 所属部门 | 硬件产品研发中心\交通与停车产品业务部 | 国际业务中心\项目方案部 |
| 缺陷ID 前缀 | `BGF`×16 / `BGA`×12 / `BGH`×2 | `BGA`×28 / `BGH`×2 |
| 全空列 | **52** | **53** |

> `OBS-1` 单批次 = 单项目 = 单仓单版本。`repoUrl` / `branch` 是 **run 级**输入，不是 defect 级。

### 1.2 状态与结论枚举（比现有代码假设的更宽）

`解决结论`：

| 值 | 配套 | hcp |
|---|---|---|
| `Solved` | 17 | 13 |
| `Delay` | 11 | 9 |
| `Unaccept` | 2 | 0 |
| `Accept` | 0 | **2** |
| `Not a bug` | 0 | **1** |
| 空 | 0 | **5** |

`缺陷状态`：`Closed` / `Open` / `Delay` / `Delay/A bug` / `Delay/A bug（自动）`。样本中**未出现 `New`**，需确认平台是否存在该值。

`当前状态`（**工作流节点，不是业务状态**）：

| 值 | 配套 | hcp |
|---|---|---|
| `已完成` | 18 | 14 |
| `挂起` | 11 | 2 |
| `3、解决缺陷【解决人】` | 0 | **13** |
| `4、审核搁置缺陷` | 0 | 1 |
| `3、验证【验证人】` | 1 | 0 |

> `OBS-2` `解决结论` 不能作为过滤条件：未解决的单子本就无结论（hcp 6 条 Open 中 5 条为空、1 条为 `Delay`）。过滤只能看 `缺陷状态`。
>
> `OBS-3` `缺陷状态 = Open` 只表示"未解决"，**不表示"无人认领"**：hcp 的 6 条 Open 里 5 条已处于 `3、解决缺陷【解决人】`，且均已指派到具体的真人解决人。

### 1.3 过滤到 Open/New 后的真实输入

| 文件 | 总行 | `Open/New` |
|---|---|---|
| 配套-交通项目 | 30 | **1**（`BGH260008050`） |
| hcp巡检 | 30 | **6** |

hcp 的 6 条（全部为真实待办样本，后文验证能力推演以此为准）：

| 缺陷ID | 级别 | 当前状态 | 标题（截断） |
|---|---|---|---|
| `BGA260061551` | 中 | 3、解决缺陷 | `[智能巡检_APP] [Android] …点击Create Issue，抓图失败` |
| `BGA260060855` | 低 | 3、解决缺陷 | `[智能巡检_通用] 工作台任务待办提交，返回的界面非对应待办…` |
| `BGA260060587` | 中 | 3、解决缺陷 | `[智能巡检_报表] 单门店报表巡检任务报表重置后，导出失败` |
| `BGA260059805` | 低 | 4、审核搁置 | `[智能巡检_视频配置] 巡检未解决的多语言UI问题` |
| `BGA260059782` | 低 | 3、解决缺陷 | `[智能巡检_任务] 远程或现场任务下重置，未区分任务模式` |
| `BGA260058637` | 低 | 3、解决缺陷 | `[智能巡检_资产配置] 其他界面返回资产，资产展开偶现无属性无资产` |

> `OBS-4` 真实批次规模为个位数 → 聚类的"减量"价值下降（不再有 30 → 30 的问题），但**去重**与**同文件合并**价值保留（见 `OBS-8`）。

---

## 2. 缺陷对象形状（三档稳定性）

### A 档：永远存在，必须进 schema

| 字段 | 覆盖 | 说明 |
|---|---|---|
| 缺陷ID | 30/30 | 12 位（前缀 3 + 数字 9）；单元格带 `flowInstId` 超链接，是回查附件/原单的唯一钥匙 |
| 标题 | 30/30 | 常带 `[模块]` 前缀：`[抓拍参数]` / `[智能巡检_任务]` / `[安全]` |
| 缺陷描述 | 30/30 | **唯一信息源**，见 §3 |
| 缺陷状态 | 30/30 | 见 `OBS-2` |
| 类型 | 30/30 | `缺陷` / `建议` |
| 严重级别 | 28/30 | `低/中/高`，会空 |
| 产品名称 / 产品版本 | 30/30 | 批次内同值 |
| 项目编号 / 项目名称 | 30/30 | 批次内同值 → `repoUrl` 映射键 |
| 检出活动 | 30/30 | `系统测试` / `软件集成测试` |
| 质量特性 | 28/30 | `功能性` / `安全性` / `易用性` |
| 解决人员 / 发现人员 / 申请人 | 30/30 | 判断"是否已有真人认领" |
| 申请时间 / 结项时间 | 30/30 | 批次窗口 |

### B 档：有时有，作增强信号

| 字段 | 配套 | hcp | 设计用法 |
|---|---|---|---|
| 所属模块 | 28/30，**仅 1 层**（`字符叠加`/`其他`×7） | 22/30，**3 层**（`HikCentral Professional/WEB/智能巡检`×14） | 3 层可直接当目录；1 层需靠标题前缀兜底 |
| 测试模块 | 14/30 | 28/30 | 模块信号第二优先 |
| 当前状态 | 30/30 | 30/30 | 已认领判定（`OBS-3`） |
| 解决人处理意见 | 10/30 | 19/30 | 可能有真人初步分析 |
| 初步定位（描述内） | 4 次出现，**全部为"无"** | 1 次，有真内容 | 按**值**判断有效性，不能按 key 判断 |
| 解决方法 | 1/30 | 13/30 | 未解决的单一律没有（见 `OBS-5`） |
| 引入原因 | 17/30 | 1/30 | 配套的 17 条 = **16 条同一枚举值 + 1 条「其他」**，信息量≈0 |
| Delay原因 / 遗留处理意见 | 11 / 11 | 9 / 8 | 判断"该不该修"的旁证 |

> `OBS-5` **字段填充率 ≠ 信息量**。配套 `引入原因` 填充 17/30，其中 16 条是同一枚举值
> `逻辑错误或不合理（异常考虑不足：线程交互异常、死循环、CPU异常占用等）`，另 1 条为 `其他`；
> hcp `解决方法` 13/30 = **7 条纯样板（`修改代码逻辑`）+ 6 条含实际内容**，后 6 条中有 5 条是
> 「`修改代码逻辑` + 追加因果」的拼接，只有 1 条完整成段。真正可用的真值如下：
>
> | 缺陷ID | 真值内容 |
> |---|---|
> | `BGA250770449` | `详细原因：二次编辑时，图片路径中没有设定的标记以及没有.jpg的后缀，导致的路径处理逻辑出错 / 修改方案：清理图片时只清理文件，不清理路径` |
> | `BGA250769894` | `展开问题列表的时候没传对应的巡检对象ID` |
> | `BGA250769726` | `vue3路由跳转错误` |
> | `BGA250766745` | `vue3升级导致` |
> | `BGA250766540` | `修改参数传参` |
> | `BGA250770661` | `确认是误报，not处理`（对应 `Not a bug`） |

### C 档：永远缺失（不要再指望）

```
✗ stackTrace（报错堆栈）
✗ pageUrl / 代码路径 / 函数名 / 文件名
✗ 图片、视频的实际内容（手动导出不含附件）
✗ 复现脚本 / 自动化用例
✗ 受影响代码版本与缺陷版本的对应关系
```

> `OBS-6` `RootCauseArtifact` 中 `evidence` / `relevant_repo` 的合法来源必须被限定为三处：**描述文本 + 附件图 + 仓库实际代码**。否则模型会凭空编造证据 —— 这是 IRON LAW 落地时的最大漏洞。

---

## 3. `缺陷描述` 的结构化价值

实测两种模板并存，**都必须支持**。

### 模板 1：用例式（配套 11/30，hcp 13/30 含 `实际结果`）

```
用例名称：… / 前置条件：… / 操作步骤：… / 测试数据：… / 预期结果：… / 实际结果：… / 问题：… / 初步定位：… / 建议：…
```

段落出现次数：

| 段落 | 配套 | hcp |
|---|---|---|
| 用例名称 | 11 | 5 |
| 前置条件 | 11 | 8 |
| 操作步骤 | 11 | **14** |
| 测试数据 | 11 | 2 |
| 预期结果 | 11 | 6 |
| **实际结果** | 11 | **13** |
| 问题： | 7 | **24** |
| 补充： | 0 | **8** |
| 初步定位 | 4（全为"无"） | 1（有真内容） |
| 建议： | 4 | 1 |

### 模板 2：自由式（hcp 主导，`问题：` + 编号列表 + `补充：` + 附件引用）

例（`BGA260059782`）：

```
问题：远程或现场任务下重置，未区分任务模式
1.任务待办选择远程任务tab，点击重置，可包含现场任务
2.任务待办选择现场任务tab，点击重置，可包含远程任务（见下图）
```

### 语义映射（设计结论）

| 描述段落 | 去向 |
|---|---|
| `实际结果` | 症状主体（替代当前把整段裸文本塞进 prompt 的做法） |
| `预期结果` | `SolutionArtifact.acceptance_criteria` 种子 |
| `操作步骤` / `前置条件` | `RootCauseArtifact.reproduction_steps` 种子 |
| `补充：` | 影响范围（如"自主巡检和事件复核均存在该问题"）—— **常是最关键的范围信息** |
| `初步定位` | 仅当值 ≠ `无` 时采纳 |
| `建议：…如其他项目或产品中存同样缺陷，请说明` | 模板占位残留，**必须剥离** |

### 描述质量分布

```
配套：长度 [12,13,13,13,14,15,16,16,16,17,19,19,22,22,23,30,69,69,104,124,204,…,624]
      └ 其中 13/30 条 描述 === 标题（完全无独立信息）
hcp ：长度 [19,19,22,27,55,60,67,76,83,87,97,98,116,…,550]
      └ 0 条 描述 === 标题
```

> `OBS-7` 描述质量决定 `needs_more_context` 的比例。「描述=标题」应作为**可计算信号**（如 `descriptionTooThin`）参与 fixability 判断，而不是让模型自由发挥。

### 数据清洗项

| 问题 | 实例 | 处理 |
|---|---|---|
| HTML 实体未解码 | `&ldquo;` `&rdquo;` `&nbsp;` | `unescapeHtml` |
| 不换行空格 | `\xa0`（历史导出大量出现） | 归一化 |
| 单元格内换行 | 描述 / 测试环境 | 保留但归一化 |
| 模板占位残留 | `问题：1.2.` / `建议：1.2.如其他项目或产品中存同样缺陷，请说明` | 剥离 |
| 同源重复单 | `BGA250770157/158/159`（标题+描述逐字一致，同报告地址） | 聚类前去重 |

---

## 4. 重复度与聚类（`OBS-8`）

### 4.1 重复缺陷实测

| 文件 | 完全重复（标题+描述归一化全等） | 近似重复 |
|---|---|---|
| 配套 | 0 组 | 0 组 |
| hcp | **1 组 3 条**：`BGA250770157/158/159`（`[安全] WebScan扫描有3个中危漏洞…`，同 `报告地址 STG-MASKED`） | **1 组**：`BGA260060855`(Open) 与 `BGA250766745`(Solved)，同为「工作台待办返回界面非对应待办」 |

### 4.2 三种聚类策略实测对照

| 策略 | 配套 | hcp |
|---|---|---|
| A. 现有规则（`deriveFingerprint` 标题 hash） | **30 簇** | 26 簇 |
| B. 先按 `标题+描述` 完全去重 | 30 条（合并 0） | 28 条（合并 2） |
| C. 去重 → 按模块分桶 → `MAX_CLUSTER_SIZE=5` 切片 | **13 桶 → 14 簇** | **12 桶 → 13 簇** |

C 方案分桶实测：

```
配套-交通                                     hcp巡检
 字符叠加(10)        → 2 簇                 智能巡检_任务(6)  → 2 簇
 抓拍参数(5)         → 1 簇                 软件成分分析(3)   → 1 簇
 安全(3)             → 1 簇                 智能巡检_问题(3)  → 1 簇
 快速配置(2)         → 1 簇                 智能巡检_事件(3)  → 1 簇
 视频电警(2)         → 1 簇                 智能巡检_APP(2)   → 1 簇
 其余各 1 簇                                其余各 1 簇
```

### 4.3 现有规则为何必然失效

`src/pipeline/aggregate.ts` 的两级规则在无栈数据上全部退化：

| 规则 | 依赖 | 无栈时 |
|---|---|---|
| 一级：`repoUrl + fingerprint` | `deriveFingerprint()` = `title + pageUrl + stackSignature + stack前200字`（`src/pipeline/normalize.ts`） | `pageUrl`/`stackTrace` 恒为 `undefined` → 指纹塌缩为标题 hash |
| 二级：`sameRepoFile()` | `topAppFrame(stackTrace)`（`src/pipeline/stack-frame.ts`） | 恒返回 `undefined` → **永不并簇** |

> `INV-1` 无栈不是 fallback，是**唯一路径**。聚类必须改为：`去重 → 模块分桶 → 中文 token 相似度 → 大小上限`。

### 4.4 模块信号的取值优先级

`所属模块` 的可靠性**因批次而异**（配套 `其他`×7 为噪声；hcp 14/30 是三层路径），而 `标题[]前缀` 与 `测试模块` 在两者中都稳定。

> `INV-2` 取模块的优先级：**`标题[]前缀` > `测试模块` > `所属模块`**。

---

## 5. 附件：真实输入的一等公民

### 5.1 引用率（悬空引用）

| 范围 | 引用 `见附件` / `见下图` / `录屏` / `视频` 的比例 |
|---|---|
| 配套 全量 | 5/30（17%） |
| hcp 全量 | 13/30（43%） |
| **hcp 仅 Open** | **3/6（50%）** |

受影响的三条恰是最需要看图的：

```
BGA260061551  …点击Create Issue，抓图失败 … 见附件视频
BGA260060855  …返回的界面非对应待办…      见附件视频
BGA260059782  …重置未区分任务模式（见下图）
```

> `OBS-9` 手动导出模式下，描述里的附件引用是**悬空**的。当前 analyze prompt 未声明"附件不可读"，模型会假设自己看到了全部证据 → 产出"看起来很有道理但完全修错"的 MR。这是本批输入最大的幻觉风险源。

### 5.2 设计含义

1. `Defect` 需带 `attachments[]`（`kind: image|video|file`、`localPath`、`filename`、`sourceUrl`），**从 v1 schema 起就要有**——后期追加会波及 analyze prompt、artifact、报告三处。
2. 落地位置：`{runDir}/attachments/{defectId}/`（与 `clusters/{clusterId}/` 平级）。
3. 图片消费方式：`analyze` 阶段用 Claude Agent SDK 的 `Read` 工具直接读 png（SDK 原生支持读图），**不需要额外视觉 pipeline**，只需保证附件在 cwd 内可读且 `Read` 在 allowlist 中（现状已满足，`ANALYZE_TOOLS` 含 `Read`）。
4. 视频：不处理，但需显式标注 `evidenceGaps.videoSkipped = true`，而不是静默忽略。
5. 手动导出模式：`attachments: []` + `attachmentsUnavailable: true`，保证"导出输入"与"接口输入"在下游行为一致。

> `INV-3` **能力标记必须显式化**：`evidenceGaps = { attachmentsUnavailable?, attachmentsMissing?, videoSkipped?, descriptionTooThin?, stackUnavailable: true }`。它决定了 fixability 能否诚实地落在 `needs_more_context`。

---

## 6. 定位：只能靠两条链路

无栈、无代码信息 → **定位能力 = 产品价值**。

### 链路 1：模块路径 → 目录

- hcp 的 `HikCentral Professional/WEB/智能巡检` × 14 是三层产品/端/功能路径，可直接拼成仓库目录去 `Glob`/`Grep`。
- 配套的 `所属模块` 是一层且大量 `其他`，需退回 `标题[]前缀`。

### 链路 2：中文 UI 文案 → i18n key → 组件

对 i18n 化的 Vue 工程，这是**最稳定**的定位链路：

```
中文 UI 文案（"单门店报表" / "远程任务" / "重置"）
  → Grep zh-CN 语言包，命中 value
  → 取对应 i18n key
  → Grep key，命中 .vue 组件
  → 该组件即 target_files
```

已实测可直接 grep 的字面量锚点：

| 缺陷ID | 锚点 |
|---|---|
| `BGA260060587` | `Scheduled Start Time`（且描述自带定位："重置后时间范围控件被清空导致"） |
| `BGA260061551` | `Create Issue` |
| `BGA260059805` | `Reselect` |

> `OBS-10` 现有 `src/pipeline/repo-map.ts` 只提取 `export function/class/const/interface/type/enum` 符号，**完全未利用语言包**。这是定位能力上最明显的一块空白。

---

## 7. 验证边界：`verifyLevel` 必须决定交付形态

无栈 + 多为 UI/文案/偶现 → **写不出失败测试是常态**。以真实 7 条 Open 逐条推演：

| 缺陷 | 类型 | 能写失败测试 | 预期结局 |
|---|---|---|---|
| `BGA260060587` 报表重置后导出失败 | 逻辑（控件值被清空） | ✅ 状态断言 | `reproduced` → 可开 MR |
| `BGA260060855` 返回界面不对 | 路由跳转 | ✅ 跳转断言 | `reproduced` → 可开 MR |
| `BGA260059782` 重置未区分任务模式 | 筛选逻辑 | ✅ 可写 | `reproduced` → 可开 MR |
| `BGA260059805` 多语言未翻译 / `Reselect` 遮挡 | 文案 + 样式 | ❌ | `regression_only` |
| `BGA260058637` 资产展开偶现无属性 | 偶现 | ❌ flaky | `env_verify_failed` |
| `BGA260061551` Android 抓图失败 | 端侧/设备 | ❌ 无环境 | `needs_more_context` |
| `BGH260008050` 升级旧基线 404 | 兼容性 | ❌ | `needs_more_context` |

**分布**：`reproduced` 3/7（43%）、`regression_only` 2/7（29%）、不可验证 2/7（29%）。

> `OBS-11` 「没有 GREEN 就没有 MR」的门禁**证伪能力保留，证真能力归零**。`verifyLevel` 不能只是报告元数据，必须映射到交付形态：

```
reproduced       → 正常 MR（有"红变绿"证据）
regression_only  → Draft MR + 人工必审 + 明确写"为何无法复现"
不可验证         → unfixed + needs_more_context + 明确写"缺什么证据才能修"
```

现有实现已做 Draft MR（`runner.ts` 中 `draftMr ?? verifyLevel === "regression_only"`），但**缺"为何无法复现"的说明字段**——对这批数据这是必需项。

---

## 8. 目标流程与现有实现的 3 处硬冲突

目标流程（业务侧确认）：

```
用户身份 + 项目编号
   ↓ [缺陷来源接口，暂缺 → 现为手动导出 Excel]
Open/New 缺陷列表 + 附件（图片/视频）
   ↓
用户指定的 workDir（内含可本地运行的代码） + 指定的代码仓链接
   ↓
分析 → 定位 → 改码 → 验证 → 交付（MR / 双结局报告）
```

| # | 冲突 | 现状 | 目标 |
|---|---|---|---|
| `C-1` | **`workDir` 语义** | 视为空容器：自动 `git clone` 到 `{workDir}/repos/<repo>`，再 `worktree add` 到 `{workDir}/worktrees/...`（`src/workspace/git.ts::ensureRepo`） | `workDir` **已含可运行代码**；应直接在仓内 `worktree add` 隔离，**不 clone**（避免重复拉取、磁盘翻倍、与用户本地状态冲突） |
| `C-2` | **`repoUrl` 层级** | `DefectSchema.repoUrl` **必填**（`src/types.ts`） | 单批次单项目单仓 → 属 **run 级**输入；`DefectSchema.repoUrl` 应可选并回退到 run 级 |
| `C-3` | **缺"用户身份"维度** | 仅 `ANTHROPIC_API_KEY` + `GITLAB_TOKEN` | 缺陷平台需要用户身份（决定可见范围），且与代码平台凭据是**两套**，不可混用 |

> `INV-4` 需引入 `DefectSource` 抽象，收敛「身份 + 项目编号 + 拉取 + 附件 + 状态过滤」。核心只接收"已验证需要处理"的 `defects[]`，**状态过滤属于来源层，不属于核心**。

---

## 9. 待决策项（设计阶段，非实现）

| # | 决策 | 影响面 |
|---|---|---|
| `DEC-1` | `workDir` 是"代码仓本身"还是"容器目录" | 决定是否保留 clone 逻辑；影响磁盘、隔离、推送三条链 |
| `DEC-2` | "用户身份"在架构里的位置 | 新增 `DefectSource` 抽象 vs 并入现有 `config` |
| `DEC-3` | `Open` 但已处于 `3、解决缺陷【解决人】` 的单如何处理（shadow / 排除 / 照常开 MR） | 决定产物可信度与是否与真人抢工 |
| `DEC-4` | 附件（图片）是否进 v1 | 决定 `Defect.attachments` 是否进 schema 及 analyze prompt 写法 |
| `DEC-5` | 不可验证缺陷的交付形态（Draft MR 还是纯 `unfixed`） | 用户体验与"诚实的未修"取舍 |
| `DEC-6` | `缺陷状态` 完整枚举，`New` 是否真实存在 | 过滤规则的唯一依据 |

建议先定 `DEC-1` 与 `DEC-4`：这两条会连锁影响其余四项。

---

## 10. 对现有代码的影响清单（供后续拆任务用，本文不实现）

按影响面排序，仅列"必须改语义"的位置：

| # | 位置 | 要点 | 关联 |
|---|---|---|---|
| 1 | `src/pipeline/aggregate.ts` | 无栈聚合改为 `去重 → 模块分桶 → 文本相似 → 上限` | `INV-1`、`INV-2`、`OBS-8` |
| 2 | 新增 `dedupe`（聚类前） | 标题+描述归一化全等即合并 | `OBS-8` |
| 3 | 新增 `readers/description` | 模板拆解、占位剥离、HTML 实体解码、`descriptionTooThin` | `OBS-7`、§3 |
| 4 | `src/pipeline/analyze.ts` | prompt 显式声明"无栈 / 附件不可读"；证据来源白名单 | `OBS-6`、`OBS-9`、`INV-3` |
| 5 | `src/pipeline/repo-map.ts` | 增加 i18n 语言包索引（文案 ↔ key ↔ 组件） | `OBS-10` |
| 6 | `src/types.ts` | `DefectSchema.repoUrl` 可选；`attachments` / `evidenceGaps`；枚举放宽 | `C-2`、`OBS-2`、`INV-3` |
| 7 | `src/workspace/git.ts` | `workDir` 已是仓时走仓内 `worktree`，不 clone | `C-1` |
| 8 | 新增 `DefectSource` | 身份 + 项目编号 + 拉取 + 附件 + 状态过滤 | `C-3`、`INV-4` |
| 9 | `src/pipeline/deliver.ts` / 报告 | `regression_only` 增加"为何无法复现"说明字段 | `OBS-11` |
| 10 | 新增 SCA 短路 | 漏洞扫描类（`CVE-` / `.dll` / `.exe`）直接 `not_actionable`，不消耗 SDK 会话 | §1.3、`OBS-5`、`GAP-F1` |

---

## 11. 现有可修复性判定逻辑与缺口（`GAP-F*`）

> 本节回答「当前代码是怎么判断一个缺陷可不可修的」。结论：**判定权完全交给模型的一次自评，代码侧只有枚举映射**。

### 11.1 判定链路（现状）

```
analyze 阶段（只读会话，maxTurns=25，仅 Read/Glob/Grep/Skill）
  │
  ├─ prompt 的 IRON LAW（`src/pipeline/analyze.ts:65`）
  │    "No code changes without a proven hypothesis.
  │     If you cannot evidence a hypothesis,
  │     set fixability to needs_more_context or not_actionable
  │     — do NOT invent a large refactor plan."
  │
  ├─ prompt 第 4 步（`analyze.ts:83`）要求输出
  │    fixability.assessment ∈ {fixable, needs_more_context, not_actionable}
  │
  ▼
parseRootCause(extractLabeledJson(text, "ROOT_CAUSE"))
  └─ zod 校验：fixability **必填**（`agent/artifacts.ts:29`）
     缺字段 / 枚举非法 → 抛错 → reasonCode = analyze_failed
  │
  ▼
gateFromFixability(assessment)          ← 全部逻辑在 `pipeline/fixability.ts:8-24`
  ├─ "fixable"             → { status: "fixable" }
  ├─ "needs_more_context"  → { status: "unfixed", reasonCode: "needs_more_context" }
  └─ 其他（not_actionable） → { status: "unfixed", reasonCode: "not_actionable" }
  │
  ▼
processCluster（`runs/runner.ts:280`）
  if (analysis.status === "unfixed") → 立即返回 unfixed，跳过
  prepare / baseline / reproduce / implement / static / verify / review / deliver
```

判定涉及的全部代码只有三处：

| 位置 | 作用 |
|---|---|
| `src/agent/artifacts.ts:9-13, 29` | `FixabilityAssessmentSchema = { assessment: 三态枚举, reason: string.min(1) }`；`fixability` 在 `RootCauseArtifact` 中**必填** |
| `src/pipeline/fixability.ts:8-28` | `gateFromFixability` / `gateFromRootCause` —— **纯映射，无任何条件分支** |
| `src/pipeline/analyze.ts:201, 243` | 两次调用：第一次（201）仅用于决定是否触发 SOLUTION 修复回合；第二次（243）才是真判定 |

### 11.2 三态 → `reasonCode` 映射

| `assessment` | 门禁结果 | `reasonCode` | 语义 |
|---|---|---|---|
| `fixable` | 继续 | — | 有证据假设，进入改码 |
| `needs_more_context` | unfixed | `needs_more_context` | 信息不足（缺日志 / 复现环境 / 上下文） |
| `not_actionable` | unfixed | `not_actionable` | 不是代码缺陷 / 不该修 |

`reasonDetail` 直接取模型给出的 `fixability.reason`（自由文本，无结构化字段）。

### 11.3 除模型自评外的 3 个「准可修复性」机械门禁

以下 3 条不属于可修复性判断，但会让簇走向同一个下场（`unfixed`），易与可修复性混淆：

| # | 门禁 | 触发条件 | `reasonCode` | 位置 |
|---|---|---|---|---|
| 1 | SOLUTION 产物缺失 | `fixable` 但 `SOLUTION` 解析失败；已给过一次 repair 回合（禁读写工具，`maxTurns=2`）仍失败 | `analyze_failed` | `analyze.ts:202-235, 255-262` |
| 2 | 无测试命令 | `resolveVerifyPlan().test` 为空 → 无 GREEN 门禁可用，拒绝开 MR | `no_test_command` | `runner.ts:298-306` |
| 3 | 基线不可运行 | 基线 verify 失败且 `classifyVerifyFailure` 判为 `environment` / `flaky` / `bad_assertion`（`stopIterate=true`） | `env_verify_failed` | `runner.ts:342-349` |

> 门禁 1 的语义细节：模型说「可修」但写不出方案，记为 `analyze_failed` 而非 `needs_more_context` —— 刻意区分「模型能力不足」与「信息不足」。

### 11.4 可修复性通过后仍会落 `unfixed` 的出口

判定为可修 ≠ 一定交付。以下是「可修复性已通过但最终未修」的全部出口：

| 阶段 | `reasonCode` |
|---|---|
| 仓库准备 / 安装失败 | `prepare_failed` |
| 改码抛错 / scope lock 违规 | `implement_failed` |
| 静态检查新失败且预算耗尽 | `static_check_failed` |
| 验证真失败且预算耗尽；classify 判 stop | `verify_failed` / `env_verify_failed` |
| Reviewer 拒绝且预算耗尽 | `review_failed` |
| 相对基线无代码改动 | `no_changes` |
| 无 `GITLAB_TOKEN` / push 或 MR API 失败 | `push_failed` |

> 因此报告中的 `unfixed[]` 实际混合了两类对象：**「一开始就判不可修」**（可修复性范畴）与**「修到一半修不动」**（执行范畴）。当前只能靠 `reasonCode` 区分，报告层面未分栏。

### 11.5 两套引擎的一致性

`graph/cluster-graph.ts::analyzeNode` 与 `runner.ts` 语义等价：

```ts
if (analysis.status === "unfixed") {
  return { ...update, ...unfixed(s, analysis.reasonCode, analysis.reasonDetail) };
}
```

判定逻辑**无分叉**；差异仅在产物落盘顺序。

### 11.6 缺口清单

| # | 缺口 | 后果 | 关联 |
|---|---|---|---|
| `GAP-F1` | **没有规则预筛** | SCA/CVE（`curl_8.14.1`、`zlib1.dll`）、端侧、偶现类全靠模型「自觉」判 `not_actionable`。§10-10 的 SCA 短路**当前完全不存在** | §1.3、`OBS-5` |
| `GAP-F2` | **prompt 未声明证据残缺** | 模型不知道「无栈、附件不可读」，容易把「描述里没写」当成「不需要」→ 判 `fixable` 后靠猜改码 | `OBS-6`、`OBS-9` |
| `GAP-F3` | **三态缺「可修但不可验证」档** | UI/文案/偶现类（真实 7 条中的 4 条）在可修复性与可验证性之间无表达位；`fixability` 与 `verifyLevel` 完全脱耦 | `OBS-11` |
| `GAP-F4` | **`needs_more_context` 不说明缺什么** | `reason` 为自由文本，无法结构化表达「缺附件图 / 缺复现环境 / 缺基线版本 / 缺日志」 | `INV-3`、`OBS-7` |
| `GAP-F5` | **一次性判定，无回炉** | analyze 判完不再重评；implement/verify 阶段暴露「其实信息不够」时只能落 `verify_failed`，不会回退为 `needs_more_context` | `OBS-11` |

补充：判断的**输入质量本身很薄** —— `buildRepoMap` 只提供 80 个文件路径 + 40 个文件的 export 符号（`repo-map.ts`），且不索引 i18n 语言包（`OBS-10`）。模型实际是在「缺陷文本 + 一张残缺仓库地图」下做三态判定。

### 11.7 最小改动面（按影响 / 成本排序，本文不实施）

| 优先 | 改动 | 类型 | 覆盖 |
|---|---|---|---|
| 1 | prompt 显式声明 `stackUnavailable` / `attachmentsUnavailable`，并限定 `evidence` 合法来源为「描述文本 + 附件图 + 仓库实际代码」 | 纯 prompt | `GAP-F2` |
| 2 | `fixability` 增加第二维 `verifiability: { reproducible \| regression_only \| unverifiable }`，与 `verifyLevel` 对齐 | schema | `GAP-F3` |
| 3 | `needs_more_context` 结构化：`missing: ("attachment" \| "repro_env" \| "baseline_version" \| "log")[]` | schema | `GAP-F4` |
| 4 | `analyze` 之前加规则预筛：命中 `CVE-` / `.dll` / `.exe` / `软件成分分析` → 直接 `not_actionable` | 规则 | `GAP-F1` |
| 5 | 预算耗尽且失败原因偏「信息不足」时，允许一次 `needs_more_context` 重判 | 流程 | `GAP-F5` |

---

## 附录 A：真实 7 条 Open 样本原貌（调试/回归用）

### `BGH260008050`（配套，Unaccept/Open）
```
标题：[] 从提测版本550升级到550以前的基线之后，会返回404,必须要删除缓存才可以正常访问
描述（69 字）：用例名称：前置条件：操作步骤：测试数据：预期结果：实际结果：问题：1.2.初步定位：无。建议：1.2.如其他项目或产品中存同样缺陷，请说明
解决人处理意见：太早之前的版本没办法一一兼容，不做处理
```
→ 描述为纯模板空壳；无任何可定位信息。

### `BGA260060587`（hcp，Open，中）— 信息最完整的一条
```
标题：[智能巡检_报表] 单门店报表巡检任务报表重置后，导出失败
描述：用例名称：不同区域数据导出成功
     前置条件：1.进入巡检检任务报表-单门店报表 2.选择门店
     操作步骤：1.底部巡检任务展开筛选项，点击重置 2.点击导出
     实际结果：导出失败
     问题：单门店报表巡检任务报表重置后，导出失败
     初步定位：重置后时间范围（Scheduled Start Time控件）被清空导致，重新配置时间可导出成功
```
→ 自带控件级定位，是唯一接近"可直接改"的样本。

### `BGA260060855`（hcp，Open，低）
```
标题：[智能巡检_通用] 工作台任务待办提交，返回的界面非对应待办，而是之前在的巡检界面
描述：…预期结果：1.跳转到巡检待办对应的巡检任务的执行界面 2.巡检任务处理成功，返回到巡检待办-巡检任务
     实际结果：2.返回的界面在之前的巡检界面，不是巡检待办-巡检任务，见附件视频
```
→ 与 `BGA250766745`（已 Solved）为同一现象的两次提单，可作"历史修复参考"。

### `BGA260059782`（hcp，Open，低）
```
标题：[智能巡检_任务] 远程或现场任务下重置，未区分任务模式
描述：问题：远程或现场任务下重置，未区分任务模式
     1.任务待办选择远程任务tab，点击重置，可包含现场任务
     2.任务待办选择现场任务tab，点击重置，可包含远程任务（见下图）
```
→ 筛选逻辑缺陷，单测可覆盖；但需图确认 UI 表现。

### `BGA260058637`（hcp，Open，低）
```
标题：[智能巡检_资产配置] 其他界面返回资产，资产展开偶现无属性无资产
描述：前置条件：1.资产已展开 操作步骤：1.切换其他菜单，返回资产，再次展开前置条件的资产
     实际结果：1.资产展开偶现无属性无资产 问题：…问题现象：正常情况：
```
→ "偶现" + 描述末尾截断（图缺失），可复现性差。

### `BGA260061551`（hcp，Open，中）
```
标题：[智能巡检_APP] [Android] 自主按模板巡检提交后，点击Create Issue，抓图失败
描述：用例名称：对资产自主巡检 … 实际结果：抓图失败 问题：[Android] …抓图失败 见附件视频
```
→ 端侧问题 + 依赖视频，仓库内不可验证。

### `BGA260059805`（hcp，Open/Delay，低）
```
标题：[智能巡检_视频配置] 巡检未解决的多语言UI问题
描述：问题：巡检未解决的多语言问题
     1.巡检库名称重复，报错仅中文翻译，英文等多语言翻译未修改
     2.[挪威语]资产配置或查看红外时，右上角Reselect被遮挡或与规则名称重叠
```
→ 两条独立问题打包在一单（i18n + 样式），需拆。

---

## 附录 B：字段映射（Excel 111 列 → 领域对象）

仅列建议保留的列；**52 个全空列不进映射**（完整清单见 §1.1）。

| 领域字段 | Excel 列 | 层级 | 备注 |
|---|---|---|---|
| `id` | 缺陷ID | run | 超链接含 `flowInstId`，另存 `traceUrl` |
| `title` | 标题 | defect | — |
| `description.raw` | 缺陷描述 | defect | 需清洗 |
| `description.*` | （解析） | defect | 见 §3 |
| `status` | 缺陷状态 | defect | 过滤依据 |
| `workflowStage` | 当前状态 | defect | 已认领判定 |
| `severity` | 严重级别 | defect | 会空 |
| `kind` | 类型 | defect | `缺陷/建议` |
| `module` | 标题前缀 > 测试模块 > 所属模块 | defect | `INV-2` |
| `testModule` | 测试模块 | defect | — |
| `qualityCharacteristic` | 质量特性 | defect | — |
| `detectedActivity` | 检出活动 | defect | — |
| `projectId` / `projectName` | 项目编号 / 项目名称 | run | → `repoUrl` 映射键 |
| `productName` / `productVersion` | 产品名称/技术/平台 · 产品版本/版本 | run | 选仓/选分支 |
| `resolver` / `reporter` | 解决人员 / 发现人员 | defect | 认领判定 |
| `resolverComment` | 解决人处理意见 | defect | 真人初步分析 |
| `resolution` | 解决结论 | defect | 6 值，见 `OBS-2` |
| `delayReason` | Delay原因 | defect | — |
| `legacyHandling` | 遗留缺陷处理意见 | defect | — |
| `attachments` | （导出无 / 接口有） | defect | 见 §5 |
| `evidenceGaps` | （派生） | defect | 见 `INV-3` |
| `repoUrl` / `branch` | （run 级输入） | run | 见 `C-2` |

---

## 附录 C：历史导出变体（别名表依据）

同一平台存在至少三套导出，解析器需容忍：

| 文件 | 列数 | 行数 | 用途 | 关键差异 |
|---|---|---|---|---|
| `缺陷列表 (1).xlsx` / `配套-交通项目.xlsx` / `hcp巡检.xlsx` | 111 | 30 | **流程管理视图**（本次样本） | 完整字段，无栈 |
| `缺陷列表.xlsx` | 11 | 380 | 精简视图 | `类型/缺陷来源/缺陷标题/缺陷描述/缺陷ID/缺陷状态/严重级别/检出活动/解决人员/当前处理人/轮次` |
| `缺陷列表 (2).xlsx` | 5 | 545 | **前端监控聚合视图** | `category/moduleName/msg/stack/url` — 唯一带真实 `stack` 与 `url` 的导出 |

别名表（必须支持）：

| 规范字段 | 别名 |
|---|---|
| `id` | `缺陷ID` |
| `title` | `标题` / `缺陷标题` |
| `description` | `缺陷描述` / `msg` |
| `module` | `所属模块` / `moduleName` / `category` |
| `stackTrace` | （111 列版无） / `stack` |
| `pageUrl` | （111 列版无） / `url` |

> `OBS-12` 若未来能从「监控聚合视图」同步拿到 `stack` / `url`，现有 `DefectSchema` 可被完整填充、`aggregate.ts` 的两级规则也重新生效 —— 这是唯一能让定位能力质变的增量输入源，值得单独立项评估。
