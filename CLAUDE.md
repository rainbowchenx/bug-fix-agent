# CLAUDE.md

Guidance for working in this repository.

## 项目定位

`bugfix-agent`：三 Agent 缺陷分析工作流（**Python**）。

```text
Agent-1（图外：skill / prepare-batch）→ defect-batch
        │
        ▼
validate_batch → Agent-2 → validate → Agent-3 → validate
                   code-knowledge        analysis-report
```

- Agent-1 不在 LangGraph 内；入口是 `bugfix-agent` CLI（`prepare-batch` / `apply-review` / `preflight` / `xlsx-to-raw` / `self-check`），`skills/defect-batch-prepare/` 只提供操作文档（无脚本）
- 编排：LangGraph Python 只跑 Agent-2→3（`bugfix_agent/workflow/graph.py`）
- 跨段只传落盘 JSON + Pydantic 校验；Agent 之间不互相 import
- Agent-2/3 可注入仓特异性 overlay skill（`.claude/skills`、`workDir/.bugfix/skills`、`--skills-dir` / `BUGFIX_SKILLS_DIR`）；overlay 压过包内置 SOP。发现逻辑：`bugfix_agent/sdk/skill_inject.py`。写法见 `docs/prompts/agent2/`
- Agent-2 cartography / Agent-3 analyze 默认可走 Claude Agent SDK（只读）；无 key 时 heuristic 回退
- 旧 TypeScript 簇级 BugFix / npm LangGraph 路径已退役

设计文档：
- `docs/superpowers/specs/2026-11-03-three-agent-architecture.md` — 正式架构
- `docs/cartography/repo-fingerprints.md` — 仓型指纹（micro_frontend 已齐；electron / device_web 待补）
- `docs/contracts/v0.1/` — 契约
- `docs/superpowers/specs/2026-10-23-report-agent-decision-followup.md` — 语言栈 / 去 SWE / 退役 TS 决策

## 常用命令

```bash
pip install -e ".[dev]"
pip install -e ".[sdk]"          # 可选：Agent-2/3 Claude Agent SDK
pytest -q
bugfix-agent preflight --source raw.csv      # Agent-1 Step 0：列映射体检
bugfix-agent prepare-batch --product-line hc --source raw.json --out /tmp/defect-batch.json
bugfix-agent apply-review --batch /tmp/defect-batch.json --overrides review.json --out /tmp/defect-batch.json
bugfix-agent run --work-dir ./repos --product-line hc --defect-batch /tmp/defect-batch.json --posture alpha --skills-dir ./line-skills --out-dir /tmp/out
```

- Python ≥ 3.11；依赖见 `pyproject.toml`（`pydantic` / `openpyxl` / `langgraph`；SDK 为 optional extra）
- 测试在 `tests/`（pytest）；缺陷样本夹具在 `test/fixtures/defect-batch/`

## 架构要点

| 路径 | 职责 |
|---|---|
| `bugfix_agent/contracts/` | 契约 SSOT（含 `load_defect_batch`，两侧共用） |
| `bugfix_agent/cli.py` + `agent1.py` | 唯一 CLI；`main(standalone=True)` 让 exe 只挂图外 5 命令 |
| `bugfix_agent/ingest/` + `defect_batch/` | Agent-1 |
| `bugfix_agent/agents/cartographer/` | Agent-2（判型判据见 `docs/cartography/repo-fingerprints.md`） |
| `bugfix_agent/agents/analyst/` | Agent-3 |
| `bugfix_agent/sdk/` | Agent-2/3 Claude Agent SDK + overlay skill 发现 |
| `bugfix_agent/workflow/` | LangGraph 父编排 + 门禁 |
| `skills/` | Claude Code skills（纯文档 + 评测；defect-batch-prepare 无脚本，命令实现在 `cli.py`；修复侧 skill 已删） |

约束：全自动无断点；凭据只走环境变量；最小 diff / 验证驱动精神保留在仍生效的 skills 中。
