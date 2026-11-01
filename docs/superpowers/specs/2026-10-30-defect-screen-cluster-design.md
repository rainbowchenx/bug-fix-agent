# 缺陷单多轮筛选与分簇设计

> 日期：2026-10-30  
> 状态：**待评审**（本稿不接现有 `bugfix-agent` 代码；只定分析侧漏斗）  
> 依据：`docs/业务缺陷分析/defect-input-analysis/_stage1-rules.md`、`_pipeline.md`、`_run-1029.md`；实测 `.run1029/*-detail.csv`  
> 产品拍板：**主候选池 = `strict`（期望唯一）**；`L1_strict` **只统计、不设闸**（测试人员不会、也不该写代码级锚点）

---

## 0. 结论先行

| 项 | 决定 |
|---|---|
| 主候选池 | **`strict`** = 过硬淘汰后 `verdict=FIXABLE` 且 `expectQuality ∈ {explicit, inferred}` |
| 不设闸 | `anchorTier=L1` / `L1_strict` —— 仅作诊断指标与黄金对照集 |
| 流程 | **R0 体检 → R1 拆池 → R2 硬淘汰 → R3 信息质量（含 strict 切割）→ R4 三层分簇 → R5（可选）残胖兜底 → R6 排序** |
| 分簇键 | **L1 `测试模块` → L2 标题 `【】`/`[]` → L3 AI 意图类别**（表字段 `type` 仅作先验）。**禁用 `所属模块`** |
| 交付 | 漏斗表 + 簇表 + 逐条表（可复算；L3 带 `intentSource`） |

一句话：筛的是「**测试语言里期望是否唯一**」（纯规则）；簇的是「**测试模块 → 标题括注 → 意图类别**」（前两层规则，第三层 AI）；技术落点留给有仓之后的步骤，不在本漏斗强求。

---

## 1. 范围与非目标

### 1.1 范围

- 五条产品线缺陷 Excel（及同结构导出）的**离线分析漏斗**
- 输入：创建时刻可用字段（见 `_stage1-rules.md` S0）
- 输出：有序的 **strict 簇队列** + 旁路池（安全 / 硬淘汰 / 信息不足 / locatable_only）

### 1.2 非目标（本稿不做）

- 不接 `runner.ts` / 改码 / MR
- 不要求测试填代码路径、函数名、组件名
- 不用 `解决方法` / `验证结论` / `缺陷处理说明` / `所属模块` 等闭环字段
- 不把 ①-a 宽松（~97%）或 L1 当入池条件

### 1.3 两套读数（必须分开报）

| 姿势 | 分母 | 用途 |
|---|---|---|
| **α 定规则** | 功能池全状态（含 Closed） | 看漏斗形状、簇结构 |
| **β 日批模拟** | 仅 `Open`∪`New` ∩ 功能池 | 估明天真实进队量 |

---

## 2. 主候选池定义

```
strict ⇔
  属于功能池
  ∧ verdict = FIXABLE          // 过 R2 + R3a
  ∧ expectQuality ∈ {explicit, inferred}
```

| 旁路 / 对照 | 定义 | 处置 |
|---|---|---|
| `hard_reject` | C7 / C3 / C3b 等 | 永久不进主池 |
| `needs_info` | C1* / C2 / C8 等 | 可补单回流 |
| `locatable_only` | FIXABLE 但 expect 为 ambiguous/absent | 不进主池；单列「待补期望」 |
| `L1_strict` | strict ∧ anchorTier=L1 | **只统计**；可作黄金集抽样，不挡入池 |

**为什么主池不是 L1_strict**：缺陷单由测试提出，L1（错误码 / 标识符 / 系统提示原文等）在多数线仅 2%～5%，当闸会误杀业务主流。hitools L1 偏高是形态特例，不能当跨线门槛。

---

## 3. 流水线（R0–R6）

```text
原始行
  R0 体检（打标、不去分析分母）
  R1 拆池 → 功能 | 安全 | 排除
  R2 硬淘汰 → hard_reject
  R3a 信息不足 → needs_info
  R3b 期望切割 → strict（主池）| locatable_only
  R4 三层分簇（仅 strict）
       L1 测试模块（规则）
       L2 标题【】/[]（规则）
       L3 缺陷意图（AI；表字段 type 作先验）
  R5 可选：L3 后仍 oversized → 标题实词兜底或标 oversized
  R6 排序 → 有序簇队列
```

规则细节（正则、profile、豁免）以 `_stage1-rules.md` 为唯一权威；本稿只定**轮次语义、入池边界、分簇策略与交付物**。  
**边界**：进不进主池、L1/L2 结构键 → 纯规则；L3 意图类别 → AI（可复算落盘，低置信度 → `unclear`）。

---

### R0 · 数据体检

| 检查 | 失败时 |
|---|---|
| 文件去重（md5 / 缺陷 ID 交集） | 合并后再计唯一数 |
| 产品线 / 业务组切分 | 禁止混池报比例 |
| 表头按**列名**对齐（65 / 69 / 111） | 禁止按列索引 |
| `duplicateOf` 非空 | `duplicate=true`，**不剔除** |
| 统计 Open 占比 | 无 Open 时禁止推断「创建时字段」 |

产出：`样本盘点表`。本轮不减少功能分析分母。

---

### R1 · 拆池

| 条件 | 池 |
|---|---|
| `Cancel` / `Not a bug` / 流程已作废 | **排除** |
| 标题 `[安全]` 或 SCA 扫描整单（按线策略） | **安全旁路**（不进功能漏斗） |
| 其余 | **功能池** |

日批姿势 β：功能池再交 `缺陷状态 ∈ {Open, New}`。

---

### R2 · 硬淘汰（永久）

短路顺序与 `_stage1-rules` 一致：C7 → C3 → C3b（+ profile.notcode / devicePatterns）。

产出：`hard_reject`，附 `rule` id。不进入 R3。

---

### R3 · 信息质量

**R3a**（可回流）：C1a–e / C2 / C4 / C5 / C8 → `needs_info`。

**R3b**（正交切割，不改「能否定位」叙事）：

| 结果 | 条件 | 去向 |
|---|---|---|
| **strict** | FIXABLE ∧ expect 唯一 | **主候选池** |
| locatable_only | FIXABLE ∧ expect 不唯一 | 待补期望池 |

R3 之后才允许分簇；**不对 hard_reject / needs_info 做业务簇统计**（避免污染簇纯度）。`locatable_only` 可选用同一套簇键做对照表，但不进入主队列。

---

### R4 · 三层分簇（仅 strict 主池）

三层是**固定分层键**，不是「择一优先级」。`所属模块` 禁用。  
`locatable_only` 可选用同一 L1/L2 做对照表，但不进主队列、默认不跑 L3。

#### L1 · 测试模块（规则）

| 条件 | 键 |
|---|---|
| `测试模块` 非空 | `normalizeTestModule`（剥版本/回归/端别后缀） |
| 缺失 | `_unmoduled`（仍进入 L2，不整条丢弃） |

强制：

1. **不读 `所属模块`**
2. 端侧修饰合并：`（APP）`/`（H5）`/`（iOS）`/`（HPP Portal）` 等
3. `MODULE_SEMANTIC_FREE` / `SEMANTIC_FREE_TAGS` → `semanticFree=true`，进 `misc/<标签>` 或「待人工归模块」，**不单独成业务主簇**
4. 与旧口径 `INV-2`（标题前缀 > 测试模块）的关系：Agent-1 **改为分层**——测试模块恒为 L1，标题括注恒为 L2，不再互相替代

#### L2 · 标题 `【】` / `[]`（规则）

1. 从标题提取首个（或配置约定的）`[...]` / `【...】` 前缀，归一（去端侧修饰）
2. 无括注 → `_untagged`
3. led 等「模块信号弱、标题括注强」的线：L1 可能大量 `_unmoduled`，L2 承担主业务面——仍保持两层字段，便于跨线统一 schema

#### L3 · 缺陷意图（AI 意图识别）

**目的**：在 L1×L2 桶内标「哪类问题」，供拆队列与下游路由；**不替代** R1–R3 硬规则。

| 项 | 约定 |
|---|---|
| 输入 | 标题 + 蒸馏后的实际/期望/步骤 + 可选表字段 `type`（先验，非唯一真相） |
| 输出 | `intent`（封闭枚举）+ `intentConfidence` + 短 `rationale` |
| 来源标记 | `intentSource = ai \| field_fallback \| unclear` |
| 低置信 | → `intent=unclear`，不硬塞类目 |
| 批处理 | **按 L1×L2 桶批推理**（同桶多条一次请求），控成本 |
| 表字段 `type` | 仅 prior / 审计；与 AI 冲突时以 AI 为准并留 `fieldType` 对照列 |

意图枚举（首版探讨，可对齐 `CLS-*` 后冻结），示例：

`ui_layout` / `i18n` / `logic` / `data_wrong` / `perf` / `compat` / `config` / `security_scan` / `unclear`

小桶策略（配置项）：若某 L1×L2 已 ≤5 条，可「只打标、不因 L3 再拆队列」；默认仍写入 `intent` 供 R6/报告使用。

簇 ID：

```text
{productLine}::{testModule}::{titleTag}::{intent}
```

---

### R5 · 残胖兜底（可选）

R4 之后若某终态簇仍满足胖阈值（`size/|strict| > 25%` 或 `size > 40`，或软上限 15～25）：

1. 优先检查是否 L3 大量塌成 `unclear` / 单一 intent —— 先修类目或重跑意图，而非盲切  
2. 仍胖 → 对该簇用**标题实词**（去前缀与端侧词后，长度 ≥2 的中/英 token 或稳定 2-gram）做兜底子桶  
3. **禁止**用「实际结果全文相似度」做主细簇  
4. 再胖 → `oversized=true`，交人工/后续，不再自动切

簇 ID 追加：`…::{intent}::{tokenBucket}`（仅触发时）。

---

### R6 · 排序（不淘汰）

只对主池簇与簇内条目排序：

```
跨簇：
  1. 含 Open/New 的簇优先
  2. 簇内 strict 条数（大优先，频次代理）
  3. 簇内 D1/D2 占比（高优先，弱信号）
  4. 簇最新创建时间

簇内：
  1. Open/New 置顶
  2. expectQuality: explicit > inferred
  3. dlevel: D1 > D2 > D3
  4. 创建时间新→旧
  5. 严重级别仅同档微调（禁止用「高」跨档 —— 高多为 CVE）
```

`L1_strict` 命中可在同档内微提升权，**不能**把非 L1 挤出主池。

---

## 4. 五线实测形状（姿势 α · strict 主池）

> 数字由 `.run1029/*-detail.csv` 按本稿口径近似重算（排除 Cancel/Not a bug 后切 strict；与 `_run-1029` 全量口径可能差数条状态边界，以复跑脚本为准）。

| 线 | 功能池约 | FIXABLE | **strict 主池** | L1_strict（仅统计） | 原「仅模块」一级簇数 | 新三层下的预期 |
|---|---|---|---|---|---|---|
| hitools | 636 | 620 | **~503（79%）** | 92 | 13 | L2/L3 切开 `AI助手-智能配置` 等胖面；再胖走 R5 |
| led | ~308 | ~298 | **~214（69%）** | 5 | 2 | L1 弱、L2 标题括注为主；L3 意图拆校正工具大盘 |
| hcp | 209 | 193 | **~129（63%）** | 5 | 10 | L2+L3 处理 `B02_BS_回放` 类胖模块 |
| hc | ~292 | ~245 | **~149（51%）** | 4 | 36 | 模块已较散，L3 多作打标；未必触发 R5 |
| 配套 | ~193 | ~152 | **~64（33%）** | 3 | 17 | semanticFree + L2/L3；`抓拍参数` 视 L3 分布 |

> 上表「一级簇数」仍是旧口径快照；三层落盘后需按 `testModule×titleTag×intent` 复跑刷新。

**姿势 β（Open）粗估**（样本极少，仅示意）：hc strict≈5 / hcp≈10 / hitools≈7；led、配套本批 Open=0。

---

## 5. 交付物

```
每条产品线一次跑批 →
  funnel.csv          # 各轮留存 / 淘汰 reason 计数（α、β 分表或分列）
  clusters.csv        # clusterId, level(1|2|3), parentId, testModule, titleTag, intent,
                      #   size, openCount, oversized, priority
  tickets.csv         # defectId, pool, roundDropped?, clusterId, expectQuality,
                      #   anchorTier, strict, fieldType, intent, intentSource,
                      #   intentConfidence, dlevel, priority, title
  metrics.json        # 含 L1_strict 计数与占比（标明「非入池门槛」）；
                      #   intent 分布与 ai/field_fallback/unclear 占比
```

验收：

- [ ] 主池定义与 §2 一致；无条目因非代码锚点 L1 被拒入主池  
- [ ] 无 `所属模块` / 闭环字段参与判定或分簇  
- [ ] 分簇为 L1→L2→L3；筛池不含 AI；L3 有 `intentSource` 可审计  
- [ ] 残胖触发 R5 或 `oversized`；α / β 两套分母不混报  
- [ ] 与 `_stage1-rules` 冲突时改本稿或显式修订 rules，不双源

---

## 6. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| `_stage1-rules.md` | ① 规则唯一权威；本稿引用不复制正则 |
| `_pipeline.md` | 口径阶梯 / 坑 / 差异表；本稿补「主池=strict」的运营切割 |
| `_defect-ticket-reform.md` | 抬 strict 率靠改模板；本稿不替代改革 |
| `_run-1029.md` | 数字快照；复跑后以新 detail 为准 |
| 10-22 / 10-23 Agent 规格 | **本稿独立**；将来若接入 Agent，以 strict 簇队列为上游契约候选 |

---

## 7. 后续（评审通过后再做）

1. 按本稿口径出一版五线 `funnel/clusters/tickets`（L1×L2 规则 + L3 AI；可先离线）  
2. 冻结 L3 意图封闭枚举（对齐或取代散落的 `CLS-*` 叙事）  
3. 若要进 Agent：另开规格定义 ingest ↔ strict 簇队列的接口（见三 Agent 探讨备忘）

---

## 8. 评审确认项

请确认或改正：

1. 主池 = `strict`，代码锚点 L1 只统计 —— **已写入**  
2. 分簇 = **测试模块 → 标题括注 → AI 意图** —— **已按讨论改写**  
3. R5 残胖阈值：`>25%` 或 `>40` —— 是否按线调整？  
4. semanticFree 的 strict 条进 `misc` 还是强制人工归模块？  
5. L3 意图枚举首版是否采用 §R4 示例集？
