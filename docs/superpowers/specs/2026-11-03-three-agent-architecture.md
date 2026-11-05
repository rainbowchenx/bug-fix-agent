# 三 Agent 正式架构（Python）

> 日期：2026-11-03  
> 状态：**实现中 · Python**  
> 探讨基线：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)

---

## 1. 目标

松耦合工作流；**实现语言为 Python**（`bugfix_agent/`），编排引擎为 **LangGraph（Python）**；不再演进 JS 三 Agent / TS LangGraph 路径。

```text
validate → Agent-1 → validate → Agent-2 → validate → Agent-3 → validate
            defect-batch         code-knowledge        analysis-report
```

- 父图：`bugfix_agent/workflow/graph.py`（`StateGraph`：`agent1` → `agent2` → `agent3`）
- 仅落盘 artifact + Pydantic 校验跨段  
- 契约审阅稿：`docs/contracts/v0.1/`

---

## 2. 目录边界

| 路径 | 段 | 职责 |
|---|---|---|
| `bugfix_agent/contracts/` | 跨段 SSOT | Pydantic 契约 |
| `bugfix_agent/ingest/` | Agent-1 内 | 拉取 → raw-defects |
| `bugfix_agent/defect_batch/` | Agent-1 | 蒸馏/筛选/分簇 |
| `bugfix_agent/agents/cartographer/` | Agent-2 | 通读/匹配 |
| `bugfix_agent/agents/analyst/` | Agent-3 | 按条路由 + analyze 会话 / 报告 |
| `bugfix_agent/sdk/` | Agent-3（可复用） | Claude Agent SDK 适配（analyze 只读） |
| `bugfix_agent/workflow/` | 父编排 | LangGraph `StateGraph` + 进出校验门禁 |
| `bugfix_agent/http/` | S4 HTTP | FastAPI：`POST/GET /v1/runs`、落盘 `.bugfix-runs/` |
| `bugfix_agent/cli.py` | CLI | `bugfix-agent run` / `serve` |

禁止 Agent-2/3 互相 import。

---

## 3. 快速开始

```bash
pip install -e ".[dev]"
bugfix-agent run \
  --work-dir ./repos \
  --product-line hc \
  --source ./raw-defects.json \
  --posture alpha \
  --out-dir /tmp/out
pytest -q
```

---

## 4. 实现顺序

| 步 | 内容 | 状态 |
|---|---|---|
| S0 | contracts + workflow 门禁 | ✅ Python |
| S0b | 父编排迁到 LangGraph Python | ✅ `workflow/graph.py` |
| S1 | Agent-1 规则管线 | ✅ |
| S2a | Agent-2 detect/match | ✅ |
| S3a | Agent-3 outcome 路由 | ✅ |
| S3b | Agent-3 analyze 会话（Claude Agent SDK，只读） | ✅ 骨架：`bugfix_agent/sdk/analyze.py`；无 key 时 heuristic 回退 |
| S2b | Agent-2 LLM 通读加厚 | ✅ 骨架：`bugfix_agent/sdk/cartography.py`；启发式 detect/match + 可选 SDK enrich |
| S4 | HTTP / LangGraph Server（可选） | ✅ FastAPI 兼容壳：`POST/GET /v1/runs`、`GET /health`（`bugfix_agent/http/`）；LangGraph Server 部署仍可选后续 |
| S5 | 退役 TS 运行时（`src/`、npm LangGraph、修复侧 skills） | ✅ |

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-11-03 | 脚手架（曾用 TS） |
| 2026-11-03 | **切换为 Python 实现**；移除 JS 三 Agent 代码 |
| 2026-11-04 | 父编排改为 LangGraph Python `StateGraph`；CLI/`run_three_agent_workflow` 走图 |
| 2026-11-04 | Agent-3 analyze：Claude Agent SDK 只读会话 + heuristic 回退；`--analyze-mode` / `BUGFIX_ANALYZE_MODE` |
| 2026-11-04 | **S5**：删除已由 Python 三 Agent 覆盖的 TS `src/`、Vitest、npm 包与修复侧 skills |
| 2026-11-04 | **S2b**：Agent-2 cartography SDK enrich + heuristic 回退；`--cartography-mode` / `BUGFIX_CARTOGRAPHY_MODE` |
| 2026-11-05 | **S4**：FastAPI `POST/GET /v1/runs` 异步壳 + `bugfix-agent serve`；状态落 `{workDir}/.bugfix-runs/{runId}/` |
