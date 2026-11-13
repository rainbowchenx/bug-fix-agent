# 筛选分簇设计稿 vs `业务缺陷分析.zip` 对照分析

> 基线：`main` @ `79ac342`（2026-10-30）。
> 对照对象：
> - 设计稿 [`2026-10-30-defect-screen-cluster-design.md`](2026-10-30-defect-screen-cluster-design.md)
> - 压缩包 `docs/业务缺陷分析.zip`（118 文件；含五线 xlsx、`.run1029/*-detail.csv`、`defect-input-analysis/_stage1-rules.md` / `_pipeline.md` / `_run-1029.md`、规则提取产物）
> 方法：解压后按设计稿 §2 / §4 口径对五份 `*-detail.csv` **复算**，并与 zip 内权威规则文档交叉核对。
> 定位：回答「设计稿写的对不对、和压缩包证据是否一致、和既有 10-22/10-23 Agent 规格如何衔接」。**不含实现**。

---

## 0. 结论先行

| 判断 | 内容 |
|---|---|
| 设计稿与 zip 的关系 | 设计稿是 zip 内 `_pipeline` / `_stage1-rules` / `_run-1029` 的**运营切割层**：把「主候选池 = strict」钉死，并补上 R4–R6 分簇排序；**规则正则仍以 `_stage1-rules.md` 为唯一权威** |
| §4 五线数字 | **4 线完全吻合**；**配套**在「安全是否进功能分母」上差 12 条（见 §2），FIXABLE/strict 只差 1 —— 属口径标注问题，不是算错 |
| 主池选型（strict，L1 不设闸） | 与 zip 证据一致：L1 跨线仅 1.3%～14.5%，当闸会误杀主流；宽松 ①-a ~97% 无区分度 |
| 与仓库现状 | zip 引用的可执行实现 `src/defects/*.ts` **不在当前 main 仓**；仓内只有设计稿 + zip 本体。规则「权威」目前在压缩包里，不在可 checkout 的源码树 |
| 对报告型 Agent | 本稿正是备忘录里的「缺陷单蒸馏 / prefilter / 分簇」上游；接入时应以 **strict 簇队列** 为 ingest 契约候选，并**修订** 10-22 `INV-2`（模块键优先级） |

---

## 1. 压缩包里有什么（结构）

```
业务缺陷分析.zip
├── 缺陷列表demo/          # 五线原始 Excel（含 1029 重导出子集）
│   ├── hc-bug-1029/hc1..6.xlsx
│   ├── hcp-bug-1029/hcp.xlsx · hitools/hitools.xlsx · led-客户端.xlsx
│   └── 配套-交通项目1..5.xlsx · 早期 hc/hcp 副本
├── .run1029/              # 五线同跑产物（设计稿数字来源）
│   ├── *-detail.csv       # 逐条 verdict / expectQuality / strictFixable / clusterKey …
│   ├── build.py · run.ts · summary.ts
├── defect-input-analysis/ # 方法论权威
│   ├── _stage1-rules.md   # ① 规则唯一权威
│   ├── _pipeline.md       # 口径阶梯 / 坑 / 差异表
│   ├── _run-1029.md       # 本次数字快照
│   └── {hc,hcp,led,hitools,配套}*.md
└── 规则提取/              # 分线 rules / fixtures / tier2·3 / S8 / 工具脚本
```

设计稿头部写的依据路径（`docs/业务缺陷分析/defect-input-analysis/...`）对应 **解压后** 的目录；**当前仓库并未解压落盘**，只有 zip。

---

## 2. §4 数字复算（姿势 α）

复算定义（与设计稿一致处）：

```
功能池 ≈ 排除 status ∈ {Cancel, Not a bug} 后的行
FIXABLE = verdict=FIXABLE
strict  = FIXABLE ∧ expectQuality ∈ {explicit, inferred}
          （与 CSV 字段 strictFixable=true 一致）
L1_strict = strict ∧ anchorTier=L1
一级簇   = strict 上 clusterKey 去重计数
```

| 线 | 设计稿 | 复算（Cancel/Not a bug 排除；安全仍留在分母） | 判定 |
|---|---|---|---|
| hitools | 636 / 620 / **503（79%）** / L1=92 / 簇=13 | 636 / 620 / **503** / 92 / 13 | ✅ 完全一致 |
| led | ~308 / ~298 / **~214（69%）** / L1=5 / 簇=2 | 308 / 298 / **214** / 5 / 2 | ✅ |
| hcp | 209 / 193 / **~129（63%）** / L1=5 / 簇=10 | 209 / 193 / **129** / 5 / 2…10 | ✅ |
| hc | ~292 / ~245 / **~149（51%）** / L1=4 / 簇=36 | 292 / 245 / **149** / 4 / 36 | ✅ |
| 配套 | **~193** / ~152 / **~64（33%）** / L1=3 / 簇=17 | **193** / **152** / **64** / 3 / 17 | ✅（此口径） |

配套的口径陷阱：

| 口径 | 功能池 | FIXABLE | strict | 簇数 |
|---|---|---|---|---|
| A. 仅排除 Cancel/Not a bug（**设计稿 §4 用的**） | 193 | 152 | 64 | 17 |
| B. 再按 R1 把 SCA/`[安全]` 挪出功能池 | **181** | 151 | 63 | 16 |

设计稿 **R1 正文**写「安全旁路、不进功能漏斗」，但 **§4 表**用的是口径 A。差 12 条几乎全是已被 C7 判 `UNFIXABLE` 的 SCA，对 strict 几乎无影响（64→63）。  
**建议**：在 §4 脚注写明「功能池分母含已被 C7 拦下的安全单」或按 R1 改用口径 B 并改表。

### 胖簇触发（R5）复算

| 线 | 设计稿声称 | 复算（strict 内） | 是否触发 `>25%` 或 `>40` |
|---|---|---|---|
| hitools | `AI助手-智能配置` ~76% | **381/503 = 75.7%**；type 切：逻辑 270 / 文案 44 / UI 31 / AI 27 / … | ✅ 必 R5 |
| led | `LED Tool-校正工具` ~97% | **207/214 = 96.7%** | ✅ 必 R5 |
| hcp | `B02_BS_回放` ~44% | **57/129 = 44.2%** | ✅ |
| hc | 最大 ~18%，可不强制 | `T-云视频-轨迹播放` **27/149 = 18.1%** | ✅ 不触发 |
| 配套 | `抓拍参数` ~38% | **24/64 = 37.5%** | ✅ |

### 姿势 β（Open∪New ∩ 功能池）

| 线 | 设计稿粗估 | 复算 Open-strict |
|---|---|---|
| hc | ≈5 | **5** |
| hcp | ≈10 | **10** |
| hitools | ≈7 | **7**（Open 功能 7 条全进 strict） |
| led / 配套 | Open=0 | **0** |

与设计稿一致；也说明：**用全状态（α）定规则可以，用它外推「明天进队量」必须单独报 β，且样本极稀。**

---

## 3. 设计决策 vs zip 证据

| 设计决策 | zip 证据 | 是否站得住 |
|---|---|---|
| 主池 = `strict`（期望唯一），不是 L1_strict | `_run-1029`：①-b(L1) 仅 1.3%～14.5%；①-a(宽松) 79%～97% | ✅ L1 当闸会误杀；宽松 ①-a 无区分度 |
| L1 只统计、不设闸 | hitools L1 偏高（17.6%）是形态特例（代码标识符/提示语多） | ✅ 设计稿已点名，不能当跨线门槛 |
| 禁用 `所属模块` | Open 填充：hc 18.8%、hitools **0/9**、Cancel 多线 0%；Closed ~97%+ | ✅ 创建时字段铁律，三线以上验证 |
| 簇键 = `测试模块`（led 用标题前缀） | 用户确认「测试模块=功能模块」；led 无该列 | ✅；且 **否定** 10-22 `INV-2` 的「标题前缀 > 测试模块」 |
| R5：胖簇先 `type` 再实词；禁实际段全文相似 | hitools AI 簇 type 分布已验证；实际段大量复读标题（hcp 93.7%） | ✅ |
| 不对 hard_reject / needs_info 做业务簇统计 | 避免污染簇纯度 | ✅ 合理；CSV 已有 `rule` 可支撑旁路表 |
| α / β 两套分母不混报 | 配套/led 本批 Open=0，混报会得出「可修率为 0」假象 | ✅ |

---

## 4. 设计稿与 zip 权威文档的缝隙

| # | 缝隙 | 说明 |
|---|---|---|
| 1 | **路径未入库** | 设计稿引用 `docs/业务缺陷分析/...`，仓内只有 zip。评审/CI 无法直接打开 `_stage1-rules.md` |
| 2 | **`src/defects/` 失踪** | `_stage1-rules` / `summary.ts` / hitools.md 均指向 `src/defects/*.ts`（约 1250 行）。**当前 main 无此目录**——规则可执行体只存在于产生 zip 的工作树，未随 79ac342 提交 |
| 3 | **R0–R3 与 S0–S10 两套编号** | zip 内 ① 阶段是 S0 字段裁剪…S10 定位档；设计稿是 R0–R6 运营漏斗。语义可映射，但新人易混。建议设计稿加一张 R↔S 对照表 |
| 4 | **安全旁路 vs §4 分母** | 见 §2；R1 与 §4 口径差 12 条（配套） |
| 5 | **semanticFree 处置未拍板** | 配套 strict 里 semanticFree≈20/64；设计稿评审项 4 仍开放（`misc` vs 强制人工归模块） |
| 6 | **`needs_info` vs `locatable_only` 回流 SLA** | 设计有池，无「补单后如何重跑」的操作约定 |
| 7 | **与 `_run-1029` ①-b 数字的表述** | `_run-1029` 表用全量 n 做分母（含 Cancel）；设计稿用功能池。配套 ①-b 宽松 66/200=33% vs 功能池 64/193=33% —— 比例接近但绝对数不同，对外必须说清分母 |

---

## 5. 与既有 Agent 规格的衔接 / 冲突

| 既有规格 | 冲突或衔接 | 建议 |
|---|---|---|
| 10-22 `INV-2`：标题前缀 > 测试模块 > 所属模块 | **冲突**：实测应改为 **测试模块 > 标题前缀**；所属模块禁用 | 修订 `INV-2` |
| 10-22 / 10-23：`CLS-6` 不可修桶 + `suggestedAction` | 设计稿旁路更细：`hard_reject` / `needs_info` / `locatable_only` / 安全 | 映射：`hard_reject`→`not_code`/`config_or_dependency`；`needs_info`→`needs_design_input`/`needs_runtime_info`；`locatable_only` 接近「能定位但期望不清」，报告型可出 brief 但降 confidence |
| 10-23 `BOUND-2` 不筛条 | **表面冲突**：设计稿主队列只进 strict | 可调和：主队列=strict（Agent 深分析）；旁路仍出报告条目（路由标签），满足「不丢条」 |
| 决策跟进：Python LangGraph + xlsx 过渡 | zip 已有五线 xlsx + 纯函数规则雏形（TS） | 蒸馏/prefilter **优先移植规则语义到 Python**，不要从零写正则；xlsx 路径已具备 |
| 10-23 报告 6 段 | 本稿止于簇队列，不含根因/定位 | 正确分层：R0–R6 = ingest 上游；analyze 仍在有仓之后 |

---

## 6. 压缩包对「下一步做什么」的直接含义

1. **先把 zip 解压入库**（或 submodule）：至少 `defect-input-analysis/*.md` + `.run1029/*-detail.csv` + 五线 1029 xlsx，否则设计稿无法独立评审。
2. **找回或重建 `src/defects/`（或 Python 等价物）**：没有它，R2/R3 不可复跑，§4 数字会漂移。
3. **评审设计稿 §8 四项**时，配套 semanticFree 与 R5 阈值可直接用本复算表，不必再估。
4. **Agent 接入点**（设计稿 §7.3）：接口草案建议为  
   `strict_clusters[]: { clusterId, defectIds[], size, openCount, typeMix?, priority }` + 旁路 `sidecars[]`；  
   与 10-23 `analysis-report` 的 `summary.byAction` 对齐时，旁路计入 `suggestedAction` 分布即可。

---

## 7. 一句话

设计稿把 zip 里已经跑通的「期望唯一 = strict」选成了主池，并用五线 detail.csv **基本算对**；真正的缺口不是理论，而是 **规则源码与分析文档还锁在 zip 里、没进可构建的仓库树**，以及 **R1 安全旁路与 §4 分母差 12 条需要写清**。
