# Agent-1 独立包（`defect-batch-prepare`）

把缺陷导出（CSV / xlsx / JSON）变成经过校验的 `defect-batch.json`。

**这个包里只有一个可执行文件。** 不需要 Python、不需要 pip、不需要联网、不需要安装
`bugfix-agent`。Agent-1 在图外，只做「导出 → 批次」这一件事，不含 LangGraph、不含 Agent-2/3。

## 用法

```bash
cd defect-batch-prepare\scripts

# Step 0 列映射体检（每次都要跑）
agent1.exe preflight --source ..\out\export.csv

# Step 1 规则漏斗
agent1.exe prepare-batch --product-line PJ14PD20260423284 ^
    --source ..\out\export.csv --posture beta --out ..\out\01-defect-batch.rule.json

# Step 2 复核后写回（02-review.json 由人/模型读原文后手写）
agent1.exe apply-review --batch ..\out\01-defect-batch.rule.json ^
    --overrides ..\out\02-review.json --out ..\out\03-defect-batch.json
```

xlsx 源文件：

```bash
agent1.exe xlsx-to-raw --xlsx ..\out\export.xlsx --product-line PJ14PD20260423284 --out ..\out\raw-defects.json
agent1.exe prepare-batch --product-line PJ14PD20260423284 --source ..\out\raw-defects.json --out ..\out\01.json
```

其它：

```bash
agent1.exe self-check     # 打印这个 exe 编译自哪个源码版本
agent1.exe --help
```

产物 `03-defect-batch.json` 就是平台包的输入——交给 Agent-2/3 用。

## 目录

```text
agent1-standalone/
├── README.md                    本文件
└── defect-batch-prepare/
    ├── SKILL.md                 执行规程（读这个决定怎么做）
    ├── evals/evals.json         评测断言
    ├── references/              列名别名 / 命令变体 / 池语义
    └── scripts/
        └── agent1.exe           全部功能都在这一个文件里
```

## 为什么只有 exe

源码单一真源在仓库 `bugfix-agent` 里，不在这个交付包里。这样改代码只有一处，交付时
替换 `agent1.exe` 即可。

| 你想做的事 | 在哪做 |
|---|---|
| 改规则 / 修 bug | 仓库 `bugfix_agent/defect_batch/*` |
| 补列名别名 | 仓库 `bugfix_agent/ingest/field_map.py` |
| 出新 exe | 仓库根 `python packaging/build.py agent1` |

**不要试图改这个包里的逻辑**——exe 是编译产物，改不了也改不得。行为不对就回仓库修，然后
重新打包替换。

## 更新流程（唯一真源在仓库）

这个目录是仓库的**构建产物**，不手工维护。改完代码跑一条命令，仓库里的
`skills/defect-batch-prepare/` + `bugfix_agent/` 会重新打成 exe 并同步过去：

```bash
python packaging/build.py agent1 --deliver-to <交付目录>
```

同步完会自动逐字节比对交付目录与 build 产物，并拒绝任何 `.py`/`.pyc` 泄漏。
两边不一致就不会默默通过。

## exe 编译自哪个版本

```bash
agent1.exe self-check
```

```text
vendor files : 20
source       : bugfix_agent (Agent-1 subset: contracts + ingest + defect_batch)
commit       : c92cc3a
copiedAt     : 2026-11-09T06:48:07Z
mode         : frozen single-file build (hashes not verifiable at runtime)
```

`commit` 就是仓库当时的 HEAD。结果被质疑时出示这个。

## 平台

- Windows x64（在 Windows 上打包的）。
- Linux / macOS 需要在该平台上重新打包；exe 不能跨平台。
