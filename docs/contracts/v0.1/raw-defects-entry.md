# 入口：平台缺陷单 → raw-defects

> Agent-1 入口格式说明（2026-11-03）。样本：`缺陷拉取/脱敏/*.csv`

## 平台 CSV 列（当前脱敏样本）

| CSV 列 | → RawDefect | 备注 |
|---|---|---|
| `defectId` | `defectId` | 必填 |
| `defectTitle` | `title` | 必填 |
| `describle` | `description` | **平台拼写**，必须兼容 |
| `defectStatus` | `status` | Open/New/Closed/… |
| `flowStatusName` | `flowStatus` | 解决缺陷/验证缺陷/已结束 |
| `severityName` | `severity` | |
| `testModule` | `testModule` | L1 |
| `createDate` | `createdAt` | |
| `detectingActivityI18n` / `assignee` / `softName` / … | `metadata.*` | 不进筛池硬规则 |

中文 Excel 别名仍支持（`缺陷ID`/`缺陷标题`/`缺陷描述`/…）。

## 用法

```bash
# 直接吃 CSV（推荐）
bugfix-agent prepare-batch \
  --product-line hc \
  --source 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --posture beta \
  --out /tmp/defect-batch.json

# 或先转 JSON
python3 bugfix_agent/scripts/csv_to_raw_defects.py \
  --csv 缺陷拉取/脱敏/PJ14PD20260423284-assignee-87.csv \
  --product-line hc \
  --out /tmp/raw-defects.json
```

映射 SSOT：`bugfix_agent/ingest/field_map.py`。
