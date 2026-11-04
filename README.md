# bugfix-agent

三 Agent 缺陷分析工作流（**Python**）：缺陷批次准备 → 代码通读 → 按条分析报告。  
父编排为 **LangGraph Python**（`bugfix_agent/workflow/graph.py`）。契约见 `docs/contracts/v0.1/`。

```bash
pip install -e ".[dev]"
pip install -e ".[sdk]"   # optional: Agent-3 Claude Agent SDK analyze
bugfix-agent run \
  --work-dir ./repos \
  --product-line hc \
  --source raw-defects.json \
  --posture alpha \
  --out-dir /tmp/out
# Agent-3: --analyze-mode heuristic|sdk（无 ANTHROPIC_API_KEY 时默认 heuristic）
pytest -q
```

## 环境变量

见 `.env.example`：

| 变量 | 说明 |
|------|------|
| `ANTHROPIC_API_KEY` | Agent-3 SDK analyze |
| `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` | 可选 |
| `BUGFIX_ANALYZE_MODE` | `heuristic` \| `sdk` |
| `BUGFIX_ANALYZE_LIMIT` | 每跑 analyze 次数上限（空=不限） |

## 库 API

```python
from bugfix_agent import create_three_agent_graph, run_three_agent_workflow

result = run_three_agent_workflow(
    work_dir="...",
    product_line="hc",
    source="raw.json",
    posture="alpha",
)
graph = create_three_agent_graph()
```

## 文档

- 正式架构：[three-agent-architecture](docs/superpowers/specs/2026-11-03-three-agent-architecture.md)
- 决策跟进（Python LangGraph、去 SWE、退役 TS）：[decision-followup](docs/superpowers/specs/2026-10-23-report-agent-decision-followup.md)
- 报告型边界：[report-agent-design](docs/superpowers/specs/2026-10-23-report-agent-design.md)

## License

MIT
