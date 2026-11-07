# Agent-2 Cartography 评测标准（v0.1）

> 目的：让 Agent-2（`code-knowledge`）的验证**可复跑、可比较、有门槛**，避免“扫一眼像能用”的盲目冒烟。  
> 范围：只评 Agent-2；不评 Agent-1 漏斗，不评 Agent-3 根因/patch。

## 1. 评测对象

| 输入 | 说明 |
|---|---|
| `workDir` | 被测目标仓 |
| `defect-batch.json` | Agent-1 产物（或夹具） |
| `code-knowledge.json` | Agent-2 产物（heuristic 或 sdk） |
| `gold.json` | 人工金标（本标准定义） |

命令：

```bash
bugfix-agent eval-agent2 \
  --work-dir /path/to/repo \
  --defect-batch /path/to/defect-batch.json \
  --gold /path/to/gold.json \
  --cartography-mode heuristic \
  --out /tmp/agent2-eval-report.json
```

也可只对已有 `code-knowledge` 打分（不重跑）：

```bash
bugfix-agent eval-agent2 \
  --work-dir /path/to/repo \
  --code-knowledge /path/to/code-knowledge.json \
  --gold /path/to/gold.json \
  --out /tmp/agent2-eval-report.json
```

## 2. 金标格式（`gold.json`）

```jsonc
{
  "schemaVersion": "0.1.0",
  "name": "dataset-id",
  "expectedProfile": ["unknown"],   // 允许列表；实际值命中任一即 profileHit
  "expectedLanguagesAnyOf": ["typescript", "javascript"],
  "tickets": [
    {
      "defectId": "PF-1",
      "goldPaths": [
        "src/ui/PermissionModal.ts",
        "src/ui/permBridge.ts"
      ],
      // any：命中 goldPaths 任一即算 localization hit
      // all：candidates 需覆盖全部 goldPaths（更严，默认不用）
      "matchMode": "any",
      "expectEmpty": false
    },
    {
      "defectId": "PF-NEG",
      "goldPaths": [],
      "expectEmpty": true          // 负例：不应给出有效定位
    }
  ],
  "gates": {
    "requireSchemaValid": true,
    "requirePathsExist": true,
    "maxCandidates": 3,
    "minHitAt1": 0.5,
    "minHitAt3": 0.7,
    "minNegativeAccuracy": 1.0,
    "requireProfileHit": false
  }
}
```

路径匹配规则（宽松且可复现）：

1. 规范化：`\\`→`/`，去前导 `./`
2. **exact**：候选 `path`（或 `repoPath/path`）与 gold 全等
3. **suffix**：候选以 `/{gold}` 结尾，或 gold 以 `/{候选}` 结尾
4. 不使用模糊编辑距离（避免“看起来像”）

## 3. 指标定义

### 3.1 门禁指标（Gates，必须项）

| ID | 指标 | 定义 | 默认门槛 |
|---|---|---|---|
| G1 | `schemaValid` | `validate_code_knowledge` 成功 | = true |
| G2 | `pathsExistRate` | 候选文件在 `workDir` 下真实存在比例 | = 1.0 |
| G3 | `candidateCapOk` | 每票 `candidates.length ≤ maxCandidates` | = true |
| G4 | `negativeAccuracy` | `expectEmpty=true` 的票中，候选为空的比例 | ≥ `minNegativeAccuracy` |

任一 Gate 失败 → 整次评测 **FAIL**（不论 hit 多高）。

### 3.2 定位指标（Localization，核心）

仅对 `expectEmpty=false` 且 `goldPaths` 非空的票计分。

| ID | 指标 | 定义 |
|---|---|---|
| L1 | `hitAt1` | 第 1 个候选命中 gold（`matchMode=any`）的票占比 |
| L2 | `hitAt3` | 前 3 个候选任一命中 gold 的票占比 |
| L3 | `pathRecall` | 票级：命中的 gold 路径数 / gold 路径数；再对票取平均（`matchMode=all` 时更有意义） |

### 3.3 形态指标（Profile，辅助）

| ID | 指标 | 定义 |
|---|---|---|
| P1 | `profileHit` | `cartographyProfile ∈ expectedProfile` |
| P2 | `languageHit` | `techStack.languages` 与 `expectedLanguagesAnyOf` 有交集（若金标省略则跳过） |

默认 **不**把 P1 当硬门槛（很多仓合法为 `unknown`）；可用 `gates.requireProfileHit` 打开。

### 3.4 报告字段

评测报告 JSON 至少包含：

- `passed`（bool）
- `gates{}` / `metrics{}` / `perTicket[]`
- `mode` / `dataset` / `generatedAt`

## 4. 通过准则（默认）

```text
PASS ⇔
  G1 ∧ G2 ∧ G3 ∧ (G4 ≥ minNegativeAccuracy)
  ∧ (hitAt1 ≥ minHitAt1)
  ∧ (hitAt3 ≥ minHitAt3)
  ∧ (requireProfileHit ⇒ profileHit)
```

默认门槛（v0.1，启发式基线）：

| 门槛 | 值 | 说明 |
|---|---|---|
| `minHitAt1` | 0.50 | 首候选可用 |
| `minHitAt3` | 0.70 | Top-3 覆盖金标 |
| `minNegativeAccuracy` | 1.00 | 负例不得乱匹配 |
| `pathsExistRate` | 1.00 | 禁止幻觉路径 |
| `maxCandidates` | 3 | 对齐契约 A3 |

SDK 模式可用同一套金标；门槛可在 `gold.gates` 覆盖，但**同一数据集比较时门槛必须固定**。

## 5. 数据集约定

| 类型 | 位置 | 用途 |
|---|---|---|
| CI 夹具 | `test/fixtures/agent2-eval/` | 人造小仓 + gold，pytest 守门 |
| 外部样本 | 评测时临时 clone；gold 放 `docs/evals/datasets/` 或本地 | 真实仓回归，不强制 CI 拉外网 |

金标制作规则：

1. 每票先写**应打开的文件**（修 bug 会动到的路径），再跑 Agent-2  
2. 负例单独标注 `expectEmpty=true`  
3. 禁止把“整个模块目录下所有文件”塞进 gold（每票建议 ≤ 5 条 goldPaths）  
4. 金标变更需说明理由（路径重构 / 票意变更）

## 6. 明确不评什么

- Agent-1 funnel / pool 对错  
- Agent-3 根因、方案、patch  
- LLM 文案质量、耗时、token（可另开 cost 看板）  
- CodeGraph 未接入前，不把 `source=codegraph` 当必选项  

## 7. 版本

| 版本 | 日期 | 说明 |
|---|---|---|
| 0.1.0 | 2026-11-07 | 首版：Gates + hit@1/hit@3 + 负例；夹具 + CLI |
