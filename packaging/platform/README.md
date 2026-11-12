# bugfix-agent 平台包（Agent-2 → Agent-3）

上传到公司 agent 平台（支持 LangGraph）用。**不含 Agent-1**——Agent-1 是图外独立的一步，
它的产物 `defect-batch.json` 作为本图的输入。

```text
Agent-1（独立 CLI/包）          本平台包
export.csv ──> defect-batch.json ──> validate_batch ──> agent2 ──> validate_knowledge
                                                                        │
                                                          agent3 <──────┘
                                                            │
                                                    validate_report ──> analysis-report.json
```

## 平台要求对照

| 要求 | 本包 |
|---|---|
| zip 根目录有 `graph.py` | ✅ `graph.py` |
| 暴露 `build_graph()` / `graph` / `main()` 之一 | ✅ 三个都暴露，转发到 `bugfix_platform/workflow/langgraph_app.py` |
| `requirements.txt` | ✅ |
| `.env`（可选） | ✅ 由 `graph.py` import 时读取（真实环境变量优先，不会被覆盖） |
| 模型配置复用平台「模型管理」 | ✅ `BUGFIX_ANALYZE_MODE` / `BUGFIX_CARTOGRAPHY_MODE` 留空即自动跟随：env 里出现 `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` 就自动走 sdk |

## 依赖

```text
pydantic>=2.7
langgraph>=1.0
claude-agent-sdk>=0.1
```

**不需要** `openpyxl`（那是 Agent-1 的 ingest 用）。`claude-agent-sdk` 现在装进依赖：
`mode` 自动跟随时有凭据就会走 sdk，不装就永远退化 heuristic。

### 怎么确认 LLM 到底跑没跑

- 产物 `code-knowledge.secondaryHints` 里有一条 `enrich=<sdk|heuristic|sdk_fallback>; <原因>`
- 产物 `analysis-report` 每票 `localization.notes` 里有 `analyze=<同上>`
- 日志里有 `[agent2] enrich=...` / `[agent3] analyze=...`

SDK 会话还会带账单和终止原因（来自 `ResultMessage`）：

```text
enrich=sdk; turns=17; reason=completed; cost=$0.42
enrich=sdk; turns=24; reason=max_turns; cost=$1.10
enrich=sdk_fallback; no Anthropic credentials in env ...
enrich=heuristic                       # 没凭据/显式 heuristic，不产生费用
```

`reason=max_turns` 说明回合用尽。触顶会尝试从会话文本 / 再问一轮 salvage 收 JSON；仍没有则**保留启发式 baseline**，`partial=true`，`source` 仍是 `sdk`（不是 `sdk_fallback`）。

Agent-2 默认把匹配池票都送进 enrich（启发式 medium 也过，标 `heuristicUnverified` 并降权），按**进 prompt 的票数**定预算：`max_turns = BASE + PER × n`（默认 `6 + 2×n`，n≤16）。`BUGFIX_CARTOGRAPHY_MAX_TURNS` 设成正整数则改为绝对上限；`0`/`unlimited` 不限制。

CodeGraph（`@colbymchenry/codegraph`）默认开启：workDir 已有 `.codegraph/` 则挂 MCP；没有则 `codegraph init -y` 再建。`BUGFIX_CODEGRAPH=0` 关掉；`BUGFIX_CODEGRAPH_INIT=0` 只用不自动建。

`enrich=sdk_fallback` 只表示 LLM 没跑成：缺凭据 / 没装 `claude-agent-sdk` / 进程崩溃 / 成功结束但 JSON 不合契约。

## 调用

平台用图 id `three_agent`（见 `langgraph.json`）。输入 state：

```json
{
  "work_dir": "/repos",
  "product_line": "PJ14PD20260423284",
  "posture": "beta",
  "defect_batch": "<defect-batch.json 的内容或路径>",
  "open_mr": false,
  "apply_fix": false
}
```

`defect_batch` 必填——`source` 字段已废弃。约束：`skip_agent2` 必须同时 `skip_agent3`。

## 目录

```text
bugfix-agent-platform.zip
├── graph.py                    平台入口（build_graph / graph / main）
├── langgraph.json              three_agent -> ./graph.py:graph
├── requirements.txt            pydantic + langgraph
├── .env / .env.example         模式开关留空，跟平台模型管理走
├── README.md                   本文件
├── bugfix_contracts/           共享契约（与 Agent-1 同一份 schema）
├── bugfix_platform/            agents / workflow / sdk（不含 Agent-1、不含 http/cli）
└── skills/                     平台分析向 skill（Agent-2/3；不含 defect-batch-prepare）
```

## 显式不含的东西

| 不含 | 原因 |
|---|---|
| `bugfix_agent1/` | Agent-1 的 ingest / defect_batch |
| `bugfix_platform/http/` | 平台自带 Server，`serve` 子命令用不上 |
| `bugfix_platform/cli.py` | 平台走图，不走 CLI |
| `defect-batch-prepare` skill | Agent-1 的 skill，与图无关 |
| `docs/` `tests/` `test/` | 不参与运行 |

## 注意

- **不要**在 `graph.py` 或 `langgraph_app.py` 里挂 `InMemorySaver`——持久化由平台负责
- 改了 `platform/bugfix_platform/workflow/graph.py` 后必须重新打包，平台不会自动跟随

## 重新打包

```bash
python packaging/build.py platform
```
