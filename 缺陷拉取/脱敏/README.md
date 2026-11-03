# Agent-1 入口数据（脱敏导出）

本目录放**可入库**的脱敏缺陷样本。原始拉取件（含真实人名 / 账号 / 内网 IP / 明文 `flowInstId`）禁止入库，见上级 `.gitignore`。

## 平台 CSV → Agent-1 `raw-defects`

Agent-1（`defect-batch-prepare`）的 **preloaded 入口**是 `raw-defects` JSON，不是 CSV/Excel 原件。契约见：

- `docs/contracts/v0.1/defect-batch.md`（产出）
- `bugfix_agent/contracts/defect_batch.py` → `RawDefect` / `RawDefectsFile`（入口）

### 字段映射（本批英文表头）

| CSV 列 | → `RawDefect` | 说明 |
|---|---|---|
| `defectId` | `defectId` | 必填 |
| `defectTitle` | `title` | 必填 |
| `describle` | `description` | 平台拼写如此，转换器保留 |
| `defectStatus` | `status` | Open/New/Closed/… |
| `flowStatusName` | `flowStatus` | |
| `testModule` | `testModule` | 创建时字段；**禁用** `所属模块` |
| `severityName` | `severity` | |
| `createDate` | `createdAt` | |
| `testRequestId` / `softName` / `revision` | `metadata.*` | 仅透传，不参与筛池 |
| `devName` / `discoveredBy*` / `assignee` / `solvedBy` / `flowInstId` | **丢弃** | 人员与流程实例不进入口契约 |

### 已生成文件

| 源 CSV | `raw-defects`（Agent-1 入口） | 建议 `productLine` / `posture` |
|---|---|---|
| `PJ14PD20260423284-assignee-87.csv`（87 条，全 Open） | `PJ14PD20260423284-assignee-87.raw-defects.json` | `ax-hybrid` / **beta** |
| `PJ14PD20260509167-reporter-resolver-416.csv`（416 条） | `PJ14PD20260509167-reporter-resolver-416.raw-defects.json` | `PJ14PD20260509167` / alpha 定规则 · **beta** 日批 |

`agent1-out/*.defect-batch.json` 是用当前规则管线跑通后的**产物样例**（可复算，非手改）。

### 转换命令

```bash
python3 bugfix_agent/scripts/csv_to_raw_defects.py \
  --csv 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --product-line ax-hybrid \
  --out 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.raw-defects.json
```

### 喂给 Agent-1

```bash
python3 - <<'PY'
from bugfix_agent import run_defect_batch_prepare
batch = run_defect_batch_prepare(
    product_line="ax-hybrid",
    posture="beta",
    source="缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.raw-defects.json",
)
print(batch.funnel)
PY
```

或整条三 Agent 工作流：

```bash
python3 -m bugfix_agent.cli run \
  --work-dir /tmp/ws \
  --product-line ax-hybrid \
  --source 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.raw-defects.json \
  --posture beta \
  --skip-agent2 --skip-agent3 \
  --out-dir /tmp/agent1-out
```

## 本批注意

1. **87 条样本** `testModule` 全满，适合作为 beta（Open）日批冒烟。
2. **416 条样本** 约 **70% `testModule` 为空** → L1 会大量退回标题括注 / `_untagged`；alpha 看全状态漏斗，beta 才接近真实进队量（Closed 会被排除）。
3. `productLine` 目前是自由标签（写入 `clusterId` 前缀）；线别 profile 规则尚未按 `ax-hybrid` 单独配置时，走默认 `ScreenProfile`。
