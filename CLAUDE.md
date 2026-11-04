# CLAUDE.md

Guidance for working in this repository.

## 项目定位

`bugfix-agent`：三 Agent 缺陷分析工作流（**Python**）。

```text
validate → Agent-1 → validate → Agent-2 → validate → Agent-3 → validate
            defect-batch         code-knowledge        analysis-report
```

- 编排：LangGraph Python（`bugfix_agent/workflow/graph.py`）
- 跨段只传落盘 JSON + Pydantic 校验；Agent 之间不互相 import
- Agent-3 analyze 默认只读（Claude Agent SDK：`Read`/`Glob`/`Grep`）；无 key 时 heuristic 回退
- 旧 TypeScript 簇级 BugFix / npm LangGraph 路径已退役

设计文档：
- `docs/superpowers/specs/2026-11-03-three-agent-architecture.md` — 正式架构
- `docs/contracts/v0.1/` — 契约
- `docs/superpowers/specs/2026-10-23-report-agent-decision-followup.md` — 语言栈 / 去 SWE / 退役 TS 决策

## 常用命令

```bash
pip install -e ".[dev]"
pip install -e ".[sdk]"          # 可选：Agent-3 Claude Agent SDK
pytest -q
bugfix-agent prepare-batch --product-line hc --source raw.json --out /tmp/defect-batch.json
bugfix-agent run --work-dir ./repos --product-line hc --source raw.json --posture alpha --out-dir /tmp/out
```

- Python ≥ 3.11；依赖见 `pyproject.toml`（`pydantic` / `openpyxl` / `langgraph`；SDK 为 optional extra）
- 测试在 `tests/`（pytest）；缺陷样本夹具在 `test/fixtures/defect-batch/`

## 架构要点

| 路径 | 职责 |
|---|---|
| `bugfix_agent/contracts/` | 契约 SSOT |
| `bugfix_agent/ingest/` + `defect_batch/` | Agent-1 |
| `bugfix_agent/agents/cartographer/` | Agent-2 |
| `bugfix_agent/agents/analyst/` + `sdk/` | Agent-3 |
| `bugfix_agent/workflow/` | LangGraph 父编排 + 门禁 |
| `skills/` | Claude Code skills（分析向；修复侧 skill 已删） |

约束：全自动无断点；凭据只走环境变量；最小 diff / 验证驱动精神保留在仍生效的 skills 中。
