# defect-batch 阅读说明

> 落盘文件名通常是 `defect-batch.json`。  
> 代码 SSOT：`contracts/bugfix_contracts/defect_batch.py`。样例：[`samples/defect-batch.sample.json`](samples/defect-batch.sample.json)。

读这份产物时：**只信 JSON + 校验结果**，不要回查缺陷平台，也不要假设上游会话上下文。

---

## 1. 总体说明

上游把平台原始缺陷（CSV / JSON / 预置 `raw-defects`）做成一份**已筛选、已蒸馏、部分已分簇**的批次包，交给后续步骤。

```text
raw-defects  ──►  defect-batch.json  ──► 后续步骤
                      │
                      ├─ funnel     各池计数
                      ├─ clusters[] 仅 strict 簇
                      └─ tickets[]  全量票（含被筛掉的）
```

三件事要先记住：

1. **`tickets[]` 是全量**。每张原始单都会出现，用 `pool` 表示筛到哪一层。
2. **`clusters[]` 不是全量**。只有 `pool=strict` 的票进簇；其它池的 `clusterId` 为 `null`。
3. **默认工作对象是匹配池**：`strict` ∪ `locatable_only` ∪ `needs_info`。  
   `hard_reject` / `security` / `excluded` / `duplicate` **默认不匹配、不分析**。

后续步骤用匹配池票做代码定位或分析报告。旁路池仍留在 `tickets[]` 里，便于统计和人工抽查，不要当可修队列。

---

## 2. 怎么读（建议顺序）

1. 看 `schemaVersion`（当前 `"0.1.0"`）和 `productLine` / `posture`。  
   `posture=beta` 表示非 Open/New 已被打进 `excluded`；`alpha` 则状态门更松。
2. 看 `funnel`：先知道这批有多少进了主池、多少被扔掉。
3. 按票工作：遍历 `tickets[]`，用 `is_match_pool(pool)`（或手写三池判断）过滤。
4. 需要「同类缺陷」时，再用 `clusterId` 去 `clusters[]` 找同簇 `defectIds`。
5. 定位或分析时优先用蒸馏切片 `observed` / `expected` / `steps` 和 `titleTag` / `testModule` / `intent`，不要把整段原始描述当检索词。

---

## 3. 契约字段表

后续步骤以本节 + Pydantic 为准。

**用途：** 缺陷批次产物，供代码定位、分析及更后面的步骤消费。

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | string | `"0.1.0"` |
| `productLine` | string | 线别 |
| `posture` | `alpha` \| `beta` | beta = 仅 Open/New 进功能漏斗 |
| `generatedAt` | ISO string | |
| `funnel` | `Record<string, number>` | total / strict / locatable_only / needs_info / hard_reject / security / excluded / duplicate |
| `clusters[]` | cluster | **仅**含 `pool=strict` 的簇 |
| `tickets[]` | ticket | **全量**票（含各 pool） |

### clusters[]

| Field | Type |
|---|---|
| `clusterId` | string (`productLine::module::tag::intent`) |
| `testModule` / `titleTag` / `intent` | string / enum |
| `size` / `openCount` | number |
| `defectIds[]` | string |

另有可选：`oversized`（切完仍大于绝对阈值）、`priority`。

`clusterId` 完整形态：

```text
{productLine}::{testModule}::{titleTag}::{intent}[::{tokenBucket}]
```

末段 `tokenBucket` 只在簇过肥被再切时出现。

### tickets[]

| Field | Type | Notes |
|---|---|---|
| `defectId` / `title` | string | 必填 |
| `pool` | enum | 见漏斗 |
| `clusterId` | string? | 仅 strict 有 |
| `testModule` / `titleTag` / `intent` | ? | L1/L2/L3 |
| `expectQuality` | enum | explicit/inferred/ambiguous/absent |
| `observed` / `expected` / `steps` | string? | 蒸馏切片 |
| `reasonCode` / `reasonDetail` | string? | 非 strict 时常有 |
| `status` / `severity` / … | ? | 透传 |

**禁止字段：** `所属模块` 等闭环字段不得进入契约。

---

## 4. 字段语义补全

### 4.1 `pool`（漏斗）

| Pool | 含义 | 后续步骤默认 |
|---|---|---|
| `strict` | 可修且预期明确（`expectQuality` ∈ explicit / inferred） | **匹配 + 分析**；有簇 |
| `locatable_only` | 可修但预期不唯一 | **匹配 + 分析**；无簇 |
| `needs_info` | 信息缺口（过薄、设计未定、附件缺失等） | **匹配 + 分析**（常走补信息结局） |
| `hard_reject` | 非代码 / SCA+CVE 等硬淘汰 | 跳过 |
| `security` | 标题 `[安全]` 或扫描器语料 | 跳过 |
| `excluded` | 作废 / 不是缺陷；或 beta 下非 Open/New | 跳过 |
| `duplicate` | 重复单 | 跳过 |

### 4.2 L1 / L2 / L3

| 字段 | 层 | 来源 | 缺省 |
|---|---|---|---|
| `testModule` | L1 | 规则归一「测试模块」（剥版本/回归/端别） | `_unmoduled`；语义空模块为 `misc/…` |
| `titleTag` | L2 | 标题 `【】` / `[]` | `_untagged`；`问题描述:` 开头为 `_code_review` |
| `intent` | L3 | 规则层先用启发式关键词；复核后可为 AI 理解 | 仅 strict（及可选 locatable / 复核过的票）有值；否则 `null` |

`intent` 封闭枚举：`ui_layout` · `i18n` · `logic` · `data_wrong` · `perf` · `compat` · `config` · `security_scan` · `crash` · `unclear`。

伴随字段：`intentSource`（`ai` / `heuristic` / `field_fallback` / `unclear`）、`intentConfidence`（`high` / `medium` / `low`）、`intentRationale`。规则管线默认写下 `heuristic`；准备步骤若按原文复核过分类，应为 `ai`。

缺 `titleTag` / `testModule` / `intent` 时，代码匹配置信度应封顶 **medium**。

> **平台导出上 L1 与 L2 通常就是同一个值。** 标题前缀 `[模块名]` 与「测试模块」列同源，实测五份导出里 `titleTag == testModule` 的比例是 5/5、21/26、19/19、36/37、54/56（96–100%）。因此 `clusterId` 的 `module::tag::intent` 实际是 `module::module::intent`，分辨率只来自 `intent` 这一维。读产物时**不要把 L1/L2 当成两个互相印证的独立证据**；只有括号名与模块列不同时（例如 `[WEB]` 而模块列是 `WEB基础组(正式批)`）L2 才携带额外信息。
>
> 实现备注：`filter_existing_candidates` 用只带 `defectId` / `title` / `pool` / `expectQuality` 的 stub 复算 confidence，因此当前**一律封顶 medium、`high` 不可达**。别把 medium 读成“证据不足”。

### 4.3 `expectQuality`

| 值 | 含义 |
|---|---|
| `explicit` | 有可对照的预期或基线 |
| `inferred` | 标题/预期里能读出「应该怎样」 |
| `ambiguous` | 有对象/现象但预期不唯一 |
| `absent` | 几乎没有可用预期 |

`strict` 只收 explicit / inferred；其余可修票进 `locatable_only`。

### 4.4 蒸馏切片与透传

- `observed` / `expected` / `steps`：从描述模板拆出；可能为空。检索代码时用这些短切片，不要回填整份 `description`（产物里也不再带原始长描述）。
- `status` / `severity` / `createdAt` / `fieldType`：透传，供姿态与报告；不要当模块路径。
- `reasonCode` / `reasonDetail`：非 strict 时常说明为什么被分流。**复核改池后会被清空**（旧筛因已过期；复核理由记在 review.json，不写在票上）。
- `semanticFree`：测试模块本身没有产品语义（如「其他」「checklist」）。
- `priority`：仅 strict 票有排序权重。
- `duplicate`：是否重复单。

---

## 5. 后续步骤该做什么 / 不该做什么

| 做 | 不做 |
|---|---|
| 先 `validate_defect_batch` 再消费 | 带病 JSON 往下传 |
| 默认只处理匹配池三档 | 把 `hard_reject` / `security` / `excluded` 当可修队列 |
| 用 `testModule` + `titleTag` + `intent` + 蒸馏切片做软定位 | 发明文件路径；用 `所属模块` |
| 空候选可以 `confidence=low` 交出去 | 要求每张票都必须有代码命中 |
| 信息不足时仍给出完整结论（分类阻断即可） | 因旁路池票缺失而失败整批 |

过滤匹配池可用 `is_match_pool(pool)`（`bugfix_contracts`）。

---

## 6. 校验

进出都必须过 Pydantic：`validate_defect_batch`。失败则硬停该步，不得把半成品交给下一步。
