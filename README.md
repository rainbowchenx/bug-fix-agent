# bugfix-agent

本地 **三 Agent 缺陷分析** 工作流（Python ≥ 3.11）。Agent-1 在图外（skill + Claude Code / `prepare-batch`）；LangGraph 只编排 Agent-2→3。默认**只分析、不出 MR**。

```text
source (CSV/JSON/xlsx)
        │
        ▼  Agent-1（图外：skill / prepare-batch）
   defect-batch.json
        │
        ▼
┌─ LangGraph 父编排（bugfix_agent/workflow）──────────────┐
│  validate_batch → Agent-2 → validate → Agent-3 → validate │
│                      │                    │               │
│                code-knowledge      analysis-report         │
└───────────────────────────────────────────────────────────┘
```

旧 TypeScript / npm / JS LangGraph 运行时已退役；本仓可执行代码只在 `bugfix_agent/`。

---

## 架构

| 组件 | 路径 | 职责 | 成熟度 |
|------|------|------|--------|
| 契约 SSOT | `bugfix_agent/contracts/` | Pydantic 校验三段 artifact | ✅ |
| Agent-1 | `ingest/` + `defect_batch/` + `skills/defect-batch-prepare/` | 图外：入口映射 → 蒸馏 / 筛选 / 分簇 → `defect-batch` | ✅ 规则管线 + skill |
| Agent-2 | `agents/cartographer/` + `sdk/cartography.py` + `skills/code-cartography/` | 仓型探测 + 形态化架构图 + 路径软匹配（候选≤3；置信度不因无 CodeGraph 封顶）+ 可选 SDK 通读 → `code-knowledge` | 🟡 启发式加厚 + SDK 骨架 |
| Agent-3 | `agents/analyst/` + `sdk/analyze.py` | 路由 + 可选 Claude 只读 analyze → `analysis-report` | 🟡 路由+SDK 骨架 |
| 父编排 | `workflow/` | LangGraph：`validate_batch→agent2→agent3` + 门禁（不含 Agent-1） | ✅ |
| HTTP（S4） | `http/` | FastAPI：`POST/GET /v1/runs`（入参 `defectBatch`）、`GET /health` | ✅ 兼容壳 |
| CLI | `cli.py` | `prepare-batch`（Agent-1）/ `run`（2→3）/ `serve` | ✅ |

**松耦合约定：** Agent 之间只交换落盘 JSON；禁止跨 Agent import 内部实现或共享 transcript。父图只调用各包公开的 `run_*` + `validate_*`。

正式规格：[docs/superpowers/specs/2026-11-03-three-agent-architecture.md](docs/superpowers/specs/2026-11-03-three-agent-architecture.md)

---

## 安装

```bash
# 建议使用 venv
python3 -m venv .venv && source .venv/bin/activate

pip install -e ".[dev]"     # 核心：pydantic / openpyxl / langgraph + pytest
pip install -e ".[sdk]"     # 可选：Agent-2/3 Claude Agent SDK（需本机 Claude Code CLI）
pip install -e ".[http]"    # 可选：FastAPI + uvicorn（S4）
```

复制环境变量模板：

```bash
cp .env.example .env
# 常用：ANTHROPIC_API_KEY、BUGFIX_ANALYZE_MODE、BUGFIX_ANALYZE_LIMIT
```

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | 有则 Agent-3 默认走 SDK analyze |
| `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` | 可选网关 / 模型覆盖 |
| `BUGFIX_ANALYZE_MODE` | Agent-3：`heuristic` \| `sdk`（显式覆盖默认） |
| `BUGFIX_ANALYZE_LIMIT` | 单次 run 最多 enrich 几张软定位票（空=不限） |
| `BUGFIX_CARTOGRAPHY_MODE` | Agent-2：`heuristic` \| `sdk`（有 key 时默认 sdk） |
| `BUGFIX_SKILLS_DIR` | Agent-2/3 额外 overlay skill 根目录（`os.pathsep` 分隔；与 `--skills-dir` 合并，overlay 优先） |

> 本机若仍有历史 `dist/`、`node_modules/`，可直接删掉（已 gitignore，不是源码）。

---

## 使用

### 1）Agent-1（图外：skill / prepare-batch）

在 Claude Code 中按 `skills/defect-batch-prepare/` 调用规则管线，或：

```bash
bugfix-agent prepare-batch \
  --product-line hc \
  --source ./raw-defects.json \
  --posture alpha \
  --out /tmp/defect-batch.json
```

`--source` 支持：

- **平台 CSV**（如 `defectTitle` / `describle` / `flowStatusName`）
- **raw-defects JSON**（见契约）
- Excel 可先用 `bugfix_agent/scripts/xlsx_to_raw_defects.py` 转 JSON

脱敏样本目录：`缺陷拉取/脱敏/`（若已入库）。夹具：`test/fixtures/defect-batch/`。

### 2）LangGraph 跑 Agent-2→3（需要已有 defect-batch）

```bash
bugfix-agent run \
  --work-dir ./path/to/target-repos \
  --product-line hc \
  --defect-batch /tmp/defect-batch.json \
  --posture alpha \
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
| `--cartography-mode heuristic\|sdk` | Agent-2 enrich 模式 |
| `--skills-dir DIR` | Agent-2/3 注入仓特异性 skill（可重复；overlay 优先于包内置；见 `docs/prompts/agent2/`） |
| `--analyze-mode heuristic\|sdk` | Agent-3 enrich 模式 |
| `--skip-agent2` / `--skip-agent3` | 调试跳过；`skip-agent2` 必须与 `skip-agent3` 同开（Agent-3 依赖 code-knowledge） |
| `--open-mr` | 仅改报告 `integrateMode` 标志；**当前不会真正开 MR** |

### 3）HTTP 服务（S4）

```bash
bugfix-agent serve --host 127.0.0.1 --port 8787
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
      "cartographyMode": "heuristic"
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
from bugfix_agent import create_three_agent_graph, run_defect_batch_prepare, run_three_agent_workflow

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
    analyze_mode="heuristic",
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

## 调试

```bash
# 单测（不需要 API key）
pytest -q
pytest -q tests/test_workflow.py tests/test_langgraph_workflow.py tests/test_analyze_sdk.py

# 只验证 Agent-1 漏斗 / 分簇
bugfix-agent prepare-batch --product-line sample --source ./your.csv --posture alpha --out /tmp/db.json
python -c "import json;print(json.load(open('/tmp/db.json'))['funnel'])"

# 强制不走 LLM，便于本地联调
bugfix-agent run ... --analyze-mode heuristic --out-dir /tmp/out

# 段失败时看 stdout 的 stage / error（agent2|agent3）
# 注入假 Agent 做单测：run_three_agent_workflow(..., agent2=..., agent3=...)
```

SDK analyze 排障：

1. `pip install -e ".[sdk]"` 且本机可跑 Claude Code CLI  
2. `.env` 中配置 `ANTHROPIC_API_KEY`  
3. 失败会 **fallback 到 heuristic**，并在票的 `localization.notes` 里标注 `analyze=sdk_fallback`

---

## 关键数据契约（v0.1）

详文与样例：[`docs/contracts/v0.1/`](docs/contracts/v0.1/) · 代码 SSOT：`bugfix_agent/contracts/`

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
- `defectCodeMatches[]`：给 Agent-3 的**软定位**起点（可空 / 低置信）

### analysis-report（Agent-3 出口）

- 每票完整报告：`localization` / `rootCause` / `proposedFix` / `blockers` / `confidence` / `verifyStatus`
- `outcome`：`plan_only` · `unlocalized` · `needs_ticket_info` · …（见契约枚举）
- 当前默认 `verifyStatus=skipped`；`openMr` 不会真正推 MR

**匹配池（默认进入 Agent-2/3）：** `strict` | `locatable_only` | `needs_info`  
（`hard_reject` / `security` / `excluded` 默认不分析）

---

## 当前不做 / 后续

| 项 | 状态 |
|----|------|
| Agent-2 CodeGraph 真工具环 / 业务形态指纹样本仓 | 后续（启发式架构图 + code-cartography skill 已落地） |
| Agent-3 出 patch / worktree 迭代 / 真 MR | 后续 |
| LangGraph Server 原生部署（S4 增强） | 后续（现有 FastAPI 兼容壳） |
| 生产 MCP 拉缺陷 | stub（现用 CSV/JSON/xlsx） |

决策背景：[decision-followup](docs/superpowers/specs/2026-10-23-report-agent-decision-followup.md)

---

## License

MIT
