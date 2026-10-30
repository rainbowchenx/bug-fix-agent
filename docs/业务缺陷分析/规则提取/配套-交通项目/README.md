# 配套-交通项目 规则提取

卡口抓拍摄像机 `V5.5.0_PJ01PR20250701315`，设备内置 Web 配置页。

## 样本

| 文件 | 行 | 说明 |
|---|---|---|
| `配套-交通项目1.xlsx` | 50 | 独立 |
| `配套-交通项目2.xlsx` | 50 | 独立 |
| `配套-交通项目3.xlsx` | 50 | **与文件 4 逐字段完全相同** |
| `配套-交通项目4.xlsx` | 50 | 同上 |
| `配套-交通项目5.xlsx` | 50 | 独立（v1.1 新增） |
| **合计** | **250 行 → 200 条唯一** | 111 列，sheet `Sheet1` |

无 `Open` 单（`Closed` 184 · `Delay` 9 · `Cancel` 7）。

## 文件

```
配套-交通项目/
├── README.md
├── rules.md                 规则 v1.1（与 hc 的 6 处实质差异 + §10 增量）
├── baseline-labels.csv      200 条人工判定（含 baselineGap / deviceSuspect 两列）
├── fixtures/defects.json    200 条输入（标题+描述+测试侧字段）
└── check-consistency.ts     与 src/defects 的一致性检查
```

## 跑

```bash
npx tsx 规则提取/配套-交通项目/check-consistency.ts            # 一致率
npx tsx 规则提取/配套-交通项目/check-consistency.ts --verbose  # 逐条差异
```

## 结果

| 指标 | 值 |
|---|---|
| 可修 | **175/200 = 87.5%** |
| 不可修 | 25（SCA 11 · VAGUE 8 · DESIGN 5 · NOTCODE 1） |
| 类型 | 逻辑 124（62%）· UI还原度 40（20%）· 文案与配置 24（12%）· 安全 12（6%） |
| 定位档 | D1 24（12%）· D2 22（11%）· **D3 154（77%）** |
| 证据缺口 | baseline 23 · description-empty 22 · expectation-empty 49 · attachment 0 |
| 一致率 | verdict **200/200** · reason **200/200** · 类型 **197/200（98.5%）** |
| 留出验证 | **未做**（199/200 此前已阅读） |

## 实现

差异收敛在 `src/defects/profile.ts` 的 `TRAFFIC_PROFILE`，与 hc 共用 `verdict.ts` / `taxonomy.ts` 骨架：

| profile 字段 | 作用 |
|---|---|
| `scaSource` / `scaVuln` | 补「软件成分分析 + HIK-VUL（无 CVE 号）」 |
| `disabledNotcode: ["plugin"]` | 「无插件」在配套是测试矩阵维度，不是产品设计结论 |
| `notcode` | 交互实现建议 |
| `design` | 「需确认需求/是否合理」 |
| `suppressVagueAdj` | 删掉 `显示不全` `多了一个` 等（配套里是真现象） |
| `inconsistencyNotVague` | 「不一致」总有两处可对照 |
| `rejectEmptyTemplate`（默认 false） | 空模板退回只看标题（D6，跨产品线通用） |
| `baselineNeed` | 记 `evidenceGaps:["baseline"]` |
| `disableCompatType` / `disablePermType` | 本产品线无这两类缺陷 |
| `typeHints` | 词表先行（缺提示→逻辑、单位/名称→文案、遮挡/缩放→UI） |
