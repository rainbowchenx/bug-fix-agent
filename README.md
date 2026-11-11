# bugfix-agent

本地 **三 Agent 缺陷分析** 工作流（Python ≥ 3.11）。Agent-1 在图外（skill + Claude Code / `prepare-batch`）；LangGraph 只编排 Agent-2→3。默认**只分析、不出 MR**。

```text
source (CSV/JSON/xlsx)
        │
        ▼  Agent-1（图外：skill / prepare-batch）
   defect-batch.json
        │
        ▼
┌─ LangGraph 父编排（platform/bugfix_platform/workflow）──┐
│  validate_batch → Agent-2 → validate → Agent-3 → validate │
│                      │                    │               │
│                code-knowledge      analysis-report         │
└───────────────────────────────────────────────────────────┘
```

旧 TypeScript / npm / JS LangGraph 运行时已退役。源码按产品切开：`contracts/`（共享契约）、`agent1/`（图外 CLI + skill）、`platform/`（LangGraph Agent-2/3 + skill）。

---

## 架构

| 组件 | 路径 | 职责 | 成熟度 |
|------|------|------|--------|
| 契约 SSOT | `contracts/bugfix_contracts/` | Pydantic 校验三段 artifact；两边唯一共享代码 | ✅ |
| Agent-1 | `agent1/bugfix_agent1/` + `agent1/skills/defect-batch-prepare/` | 图外：入口映射 → 蒸馏 / 筛选 / 分簇 → `defect-batch` | ✅ 规则管线 + skill |
| Agent-2 | `platform/bugfix_platform/agents/cartographer/` + `sdk/` + `platform/skills/code-cartography/` | 调用方仓型 + 形态化架构图 + 路径软匹配（候选≤3；无 token 不得用入口文件填票）+ overlay skill + 可选 SDK 加厚仓图/弱匹配 → `code-knowledge` | 🟡 启发式加厚 + SDK 骨架 |
| Agent-3 | `platform/bugfix_platform/agents/analyst/` + `sdk/` | 全程 SDK 分析出完整报告；`--apply-fix` 才 worktree 改码（默认关） | 🟡 报告路径可用，改码默认关 |
| 父编排 | `platform/bugfix_platform/workflow/` | LangGraph：`validate_batch→agent2→agent3` + 门禁（不含 Agent-1） | ✅ |
| HTTP（S4） | `platform/bugfix_platform/http/` | FastAPI：`POST/GET /v1/runs`（入参 `defectBatch`）、`GET /health` | ✅ 兼容壳 |
| CLI | `bugfix-agent` / `bugfix-platform` | 两个入口：Agent-1 图外命令 vs 平台 `run` / `serve` | ✅ |

**松耦合约定：** Agent 之间只交换落盘 JSON；禁止跨产品 import。父图只调用各包公开的 `run_*` + `validate_*`。

正式规格：[docs/superpowers/specs/2026-11-03-three-agent-architecture.md](docs/superpowers/specs/2026-11-03-three-agent-architecture.md)

---

## 安装

```bash
# 建议使用 venv
python3 -m venv .venv && source .venv/bin/activate

pip install -e ".[dev]"     # 两边开发：pydantic / openpyxl / langgraph + pytest
pip install -e ".[agent1]"  # 只装 Agent-1（openpyxl）
pip install -e ".[platform]" # 只装平台（langgraph）
pip install -e ".[sdk]"     # 可选：Agent-2/3 Claude Agent SDK（需本机 Claude Code CLI）
pip install -e ".[http]"    # 可选：FastAPI + uvicorn（S4）
pip install -e ".[build]"   # 要跑 packaging/build.py 编译 exe 时必须（PyInstaller）
```

复制环境变量模板：

```bash
cp .env.example .env
# 常用：ANTHROPIC_API_KEY、BUGFIX_ANALYZE_MODE、BUGFIX_CARTOGRAPHY_MODE、BUGFIX_SKILLS_DIR
```

CLI 启动时读取 **CWD 下的 `.env`**（`bugfix-agent` / `bugfix-platform` 都读，实现见
`contracts/bugfix_contracts/env.py`）。规则：

- **已存在的环境变量优先** —— 平台注入的凭据不会被仓里的 `.env` 覆盖
- 换文件用 `BUGFIX_ENV_FILE=/path/to/env`
- 不做变量展开；`BUGFIX_ANALYZE_LIMIT=` 这种空值就是空（=不限）

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | 有则 Agent-2 cartography / Agent-3 analyze 默认走 SDK |
| `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` | 可选网关 / 模型覆盖 |
| `BUGFIX_ANALYZE_MODE` | Agent-3：`heuristic` \| `sdk`（显式覆盖默认） |
| `BUGFIX_ANALYZE_LIMIT` | 单次 run 最多 enrich 几张软定位票（空=不限） |
| `BUGFIX_APPLY_FIX` | Agent-3 是否在报告后改码（`1`/`true`；默认关；等价 `--apply-fix`） |
| `BUGFIX_ANALYZE_MAX_TURNS` | Agent-3 SDK 回合上限（默认 24） |
| `BUGFIX_CARTOGRAPHY_MODE` | Agent-2：`heuristic` \| `sdk`（有 key 时默认 sdk） |
| `BUGFIX_SKILLS_DIR` | Agent-2/3 额外 overlay skill 根目录（`os.pathsep` 分隔；与 `--skills-dir` 合并，overlay 优先） |

> 本机若仍有历史 `node_modules/`，可直接删掉（TS 时代残留，不是源码；该目录已不随仓库管理）。

---

## 使用

### 1）Agent-1（图外：skill / prepare-batch）

拿到新导出先做列映射体检（出问题先看这里，`ok:true` 但 0 票时第一步）：

```bash
bugfix-agent preflight --source ./defects.csv
```

在 Claude Code 中按 `agent1/skills/defect-batch-prepare/`（纯文档）调用规则管线（规则跑完后可用 `apply-review` 回写意图复核），或：

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source ./raw-defects.json \
  --posture alpha \
  --out /tmp/defect-batch.json
```

意图复核回写（重建簇与漏斗，不要手改 `clusterId` / `funnel`）：

```bash
bugfix-agent apply-review \
  --batch /tmp/defect-batch.json \
  --overrides ./review.json \
  --out /tmp/defect-batch.json
```

`--source` 支持：

- **平台 CSV**（如 `defectTitle` / `describle` / `flowStatusName`）
- **raw-defects JSON**（见契约）
- Excel 可先用 `xlsx-to-raw` 转 JSON（`bugfix-agent xlsx-to-raw`）

脱敏样本目录：`缺陷拉取/脱敏/`（若已入库）。夹具：`test/fixtures/defect-batch/`。

### 2）LangGraph 跑 Agent-2→3（需要已有 defect-batch）

```bash
bugfix-platform run \
  --work-dir ./path/to/target-repos \
  --product-line hc \
  --defect-batch /tmp/defect-batch.json \
  --posture alpha \
  --cartography-profile micro_frontend \
  --cartography-mode heuristic \
  --skills-dir ./line-skills \
  --analyze-mode heuristic \
  --out-dir /tmp/bugfix-out
```

`--out-dir` 在成功或失败时都会尽量写入已产出的 artifact：

- `defect-batch.json`
- `code-knowledge.json`
- `analysis-report.json`

stdout 会打印摘要：`ok` / `stage` / `funnel` / `profile` / `summary`。

常用开关：

| 参数 | 含义 |
|------|------|
| `--posture alpha\|beta` | beta 时非 Open/New 更易进 `excluded` |
| `--cartography-profile electron_node\|micro_frontend\|device_web\|unknown` | Agent-2 仓型（调用方给定，不探测；省略则为 `unknown`） |
| `--cartography-mode heuristic\|sdk` | Agent-2 enrich 模式 |
| `--skills-dir DIR` | Agent-2/3 注入仓特异性 skill（可重复；overlay 优先于包内置；见 `docs/prompts/agent2/`） |
| `--analyze-mode heuristic\|sdk` | Agent-3 enrich 模式（产品路径是 sdk；heuristic 留给无 key 测试） |
| `--apply-fix` | Agent-3 在完整报告之后跑 worktree 改码（默认关） |
| `--skip-agent2` / `--skip-agent3` | 调试跳过；`skip-agent2` 必须与 `skip-agent3` 同开（Agent-3 依赖 code-knowledge） |
| `--open-mr` | 仅改报告 `integrateMode` 标志；**必须同时 `--apply-fix`**；当前不会真正开 MR |

### 3）HTTP 服务（S4）

```bash
bugfix-platform serve --host 127.0.0.1 --port 8787
```

```bash
# 创建 run（202）
curl -sS -X POST http://127.0.0.1:8787/v1/runs \
  -H 'content-type: application/json' \
  -d '{
    "workDir": "/abs/path/to/repos",
    "productLine": "hc",
    "defectBatch": "/abs/path/to/defect-batch.json",
    "posture": "alpha",
    "options": {
      "analyzeMode": "heuristic",
      "cartographyMode": "heuristic",
      "cartographyProfile": "micro_frontend",
      "skillsDirs": ["./line-skills"]
    }
  }'

# 轮询（需带同一 workDir）
curl -sS 'http://127.0.0.1:8787/v1/runs/<runId>?workDir=/abs/path/to/repos'
curl -sS http://127.0.0.1:8787/health
```

状态与产物落在 `{workDir}/.bugfix-runs/{runId}/`（`meta.json` 原子写入 + `artifacts/*.json`）。  
`runId` 仅允许 `[A-Za-z0-9._-]`，拒绝 `..` / 路径分隔，防止逃逸出 `.bugfix-runs/`。  
默认绑定 `127.0.0.1`；非 loopback host 会告警。  
响应 `schemaVersion` 为 `3-agent-0.1`（与旧 TS `fixed[]/unfixed[]` 报告不兼容）。

### 4）库调用

```python
from bugfix_agent1 import run_defect_batch_prepare
from bugfix_platform import create_three_agent_graph, run_three_agent_workflow

batch = run_defect_batch_prepare(
    product_line="hc",
    source="./raw-defects.json",
    posture="alpha",
)
result = run_three_agent_workflow(
    work_dir="./repos",
    product_line="hc",
    defect_batch=batch,
    posture="alpha",
    cartography_profile="micro_frontend",
    analyze_mode="heuristic",
    extra_skill_dirs=["./line-skills"],
)
assert result.ok and result.stage == "done"
knowledge = result.artifacts.code_knowledge
report = result.artifacts.analysis_report

# 或直接 invoke LangGraph（须自带 defect_batch）
graph = create_three_agent_graph()
final = graph.invoke({
    "work_dir": "./repos",
    "product_line": "hc",
    "posture": "alpha",
    "defect_batch": batch.model_dump(),
    "open_mr": False,
    "skip_agent2": False,
    "skip_agent3": False,
})
```

---

## 打包

同一个仓出两个产物，打包拷整个产品目录（不再维护文件白名单）：

| 产物 | 内容 | 消费者 |
|---|---|---|
| `dist/agent1-standalone.zip` | Agent-1 单文件 exe（零依赖，含 openpyxl）+ 自己的 skill | 在图外跑 `prepare-batch` / `apply-review` |
| `dist/bugfix-agent-platform.zip` | Agent-2/3 + LangGraph + 平台 skill，根目录 `graph.py` 暴露 `build_graph()` / `graph` / `main()` | 内部 agent 平台 |

两侧只共享 `bugfix_contracts`；平台包不含 `bugfix_agent1` / Agent-1 skill，Agent-1 包不含 `bugfix_platform` / 平台 skill。

先装构建依赖（只需一次）：

```bash
pip install -e ".[build]"                 # PyInstaller；缺了 build.py 会直接告诉你装什么
```

```bash
python packaging/build.py                 # 两个都打
python packaging/build.py agent1          # 只打 exe
python packaging/build.py platform        # 只打平台包

# 构建后直接同步到交付目录（推荐：别手工 cp）
python packaging/build.py agent1 --deliver-to /path/to/delivery
```

exe 的出处用 `agent1.exe self-check` 查（编译自哪个 commit）；**exe 要在提交之后编译**，否则 self-check 报的 commit 落后于 HEAD。

**真源只有本仓。** `agent1/skills/defect-batch-prepare/` 只存操作文档（SKILL.md / references / evals）；所有命令实现在 `agent1/bugfix_agent1/`；打包产物（含 `agent1.exe`）不进版本库，用上面的命令重建。`--deliver-to` 会在同步后逐字节比对交付目录与构建产物，不一致或出现 `.py`/`.pyc` 泄漏都会直接失败。

改 skill 行为时：

| 要改的东西 | 改哪里 |
|---|---|
| 筛选 / 分簇 / 意图规则 | `agent1/bugfix_agent1/defect_batch/` |
| 列名别名、xlsx 解析 | `agent1/bugfix_agent1/ingest/{field_map,xlsx_source,csv_source}.py` |
| 执行规程、评测断言 | `agent1/skills/defect-batch-prepare/`（SKILL.md / evals） |
| CLI 子命令、独立入口、双产物打包 | `agent1/bugfix_agent1/cli.py` · `packaging/build.py` |

---

## 调试

```bash
# 单测（不需要 API key）
pytest -q
pytest -q tests/platform/test_workflow.py tests/platform/test_langgraph_workflow.py tests/platform/test_analyze_sdk.py

# 只验证 Agent-1 漏斗 / 分簇
bugfix-agent prepare-batch --source ./your.csv --out /tmp/db.json
python -c "import json;print(json.load(open('/tmp/db.json'))['funnel'])"

# 强制不走 LLM，便于本地联调
bugfix-platform run ... --analyze-mode heuristic --out-dir /tmp/out

# 段失败时看 stdout 的 stage / error（agent2|agent3）
# 注入假 Agent 做单测：run_three_agent_workflow(..., agent2=..., agent3=...)
```

SDK analyze 排障：

1. `pip install -e ".[sdk]"` 且本机可跑 Claude Code CLI  
2. `.env` 中配置 `ANTHROPIC_API_KEY`  
3. 失败会 **fallback 到 heuristic**，并在票的 `localization.notes` 里标注 `analyze=sdk_fallback`

---

## 关键数据契约（v0.1）

详文与样例：[`docs/contracts/v0.1/`](docs/contracts/v0.1/) · 代码 SSOT：`contracts/bugfix_contracts/`

```text
raw-defects  ──Agent-1──►  defect-batch  ──Agent-2──►  code-knowledge  ──Agent-3──►  analysis-report
```

| Artifact | 生产者 | 消费者 | 文档 |
|----------|--------|--------|------|
| `raw-defects` | CSV / Excel / JSON 入口 | Agent-1 | [raw-defects-entry.md](docs/contracts/v0.1/raw-defects-entry.md) |
| `defect-batch` | Agent-1 | Agent-2、3 | [defect-batch-guide.md](docs/contracts/v0.1/defect-batch-guide.md) |
| `code-knowledge` | Agent-2 | Agent-3 | [code-knowledge.md](docs/contracts/v0.1/code-knowledge.md) |
| `analysis-report` | Agent-3 | 人 / 下游 | [analysis-report.md](docs/contracts/v0.1/analysis-report.md) |

### defect-batch（Agent-1 出口）

- `funnel`：`total` / `strict` / `locatable_only` / `needs_info` / `hard_reject` / `security` / `excluded` / `duplicate`
- `clusters[]`：**仅** `pool=strict` 的簇（`clusterId = productLine::module::tag::intent`）
- `tickets[]`：全量票；含蒸馏字段 `observed` / `expected` / `steps`、`expectQuality`、`reasonCode`

### code-knowledge（Agent-2 出口）

- `cartographyProfile`、`repoRoots`、`techStack`、`architecture`、`specAtlas`
- `boundSkills[]`：本次绑定的 cartography overlay（在前）+ 包内置 skill 名
- `defectCodeMatches[]`：给 Agent-3 的**软定位**起点（可空 / 低置信）

### analysis-report（Agent-3 出口）

- 每票完整报告：`localization` / `rootCause` / `proposedFix` / `blockers` / `confidence` / `verifyStatus`
- `boundSkills[]`：本次绑定的 analyze overlay（在前）+ 包内置 skill 名
- `outcome`：`plan_only` · `unlocalized` · `needs_ticket_info` · …（见契约枚举）
- 当前默认 `verifyStatus=skipped`；`applyFix=false` 只出报告；`openMr` 不会真正推 MR
- 实仓怎么打分：[`docs/field-eval/agent3/README.md`](docs/field-eval/agent3/README.md)（`packaging/eval_agent3.py`）

仓特异性 skill 写法与注入位置：[`docs/prompts/agent2/`](docs/prompts/agent2/)（Agent-3 共用，见 [`docs/prompts/agent3/`](docs/prompts/agent3/)）。`profiles: bugfix` 两边都加载；overlay 压过包内置 SOP。

**匹配池（默认进入 Agent-2/3）：** `strict` | `locatable_only` | `needs_info`  
（`hard_reject` / `security` / `excluded` 默认不分析）

---

## 当前不做 / 后续

| 项 | 状态 |
|----|------|
| Agent-2 CodeGraph 真工具环 / 业务形态指纹样本仓 | 后续（启发式架构图 + code-cartography skill 已落地） |
| Agent-3 真 MR / 本地集成冲突 | 后续（`--apply-fix` 已可出 patch 文件，默认关） |
| LangGraph Server 原生部署（S4 增强） | 后续（现有 FastAPI 兼容壳） |
| 生产 MCP 拉缺陷 | stub（现用 CSV/JSON/xlsx） |

决策背景：[decision-followup](docs/superpowers/specs/2026-10-23-report-agent-decision-followup.md)

---

## License

MIT
