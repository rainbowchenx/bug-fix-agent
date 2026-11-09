# 三 Agent 正式架构（Python）

> 日期：2026-11-03  
> 状态：**实现中 · Python**  
> 探讨基线：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)

---

## 1. 目标

松耦合工作流；**实现语言为 Python**（`contracts/` + `agent1/` + `platform/`），编排引擎为 **LangGraph（Python）**；不再演进 JS 三 Agent / TS LangGraph 路径。

```text
Agent-1（图外：skill / prepare-batch）→ defect-batch
        │
        ▼
validate_batch → Agent-2 → validate → Agent-3 → validate
                   code-knowledge        analysis-report
```

- Agent-1 **不在** LangGraph 内：`agent1/skills/defect-batch-prepare/` + Claude Code / `bugfix-agent prepare-batch`
- 父图：`platform/bugfix_platform/workflow/graph.py`（`StateGraph`：`validate_batch` → `agent2` → `agent3`）
- 仅落盘 artifact + Pydantic 校验跨段  
- 契约审阅稿：`docs/contracts/v0.1/`

---

## 2. 目录边界

| 路径 | 段 | 职责 |
|---|---|---|
| `contracts/bugfix_contracts/` | 跨段 SSOT | Pydantic 契约（两边唯一共享代码） |
| `agent1/bugfix_agent1/ingest/` | Agent-1 内 | 拉取 → raw-defects |
| `agent1/bugfix_agent1/defect_batch/` | Agent-1 | 蒸馏/筛选/分簇 |
| `agent1/skills/defect-batch-prepare/` | Agent-1 skill | 操作文档 + 评测 |
| `platform/bugfix_platform/agents/cartographer/` | Agent-2 | 通读/匹配 |
| `platform/bugfix_platform/agents/analyst/` | Agent-3 | 按条路由 + analyze 会话 / 报告 |
| `platform/bugfix_platform/sdk/` | Agent-2/3 | Claude Agent SDK 适配（cartography / analyze 只读）+ overlay skill 发现（`skill_inject.py`） |
| `platform/bugfix_platform/workflow/` | 父编排 | LangGraph `StateGraph` + 进出校验门禁 |
| `platform/bugfix_platform/http/` | S4 HTTP | FastAPI：`POST/GET /v1/runs`、落盘 `.bugfix-runs/` |
| `platform/skills/` | Agent-2/3 skill | 包内置 SOP（不含 Agent-1） |
| `bugfix-agent` / `bugfix-platform` | CLI | 两个入口，互不注册对方子命令 |

禁止 Agent-2/3 互相 import。

---

## 3. 快速开始

```bash
pip install -e ".[dev]"
bugfix-agent prepare-batch \
  --product-line hc --source ./raw-defects.json --posture alpha \
  --out /tmp/defect-batch.json
bugfix-platform run \
  --work-dir ./repos \
  --product-line hc \
  --defect-batch /tmp/defect-batch.json \
  --posture alpha \
  --skills-dir ./line-skills \
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
| S3b | Agent-3 analyze 会话（Claude Agent SDK，只读） | ✅ 骨架：`platform/bugfix_platform/sdk/analyze.py`；无 key 时 heuristic 回退 |
| S2b | Agent-2 LLM 通读加厚 | ✅ 骨架：`platform/bugfix_platform/sdk/cartography.py`；启发式 detect/match + 可选 SDK enrich |
| S2c | Agent-2 启发式加厚 | ✅ 形态化 architecture 图、A3/A4 置信度、`platform/skills/code-cartography/` |
| S4 | HTTP / LangGraph Server（可选） | ✅ FastAPI 兼容壳：`POST/GET /v1/runs`、`GET /health`（`platform/bugfix_platform/http/`）；LangGraph Server 部署仍可选后续 |
| S5 | 退役 TS 运行时（`src/`、npm LangGraph、修复侧 skills） | ✅ |
| S6 | Agent-2/3 仓特异性 overlay skill | ✅ `sdk/skill_inject.py`；`--skills-dir` / `.bugfix/skills` / `BUGFIX_SKILLS_DIR`；overlay 压过包内置 SOP |

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
| 2026-11-05 | 评审加固：`flowStatus` 进排除；`duplicate` pool；禁单独 `skip_agent2`；HTTP `runId` 防路径逃逸 + meta 原子写；Agent-2 丢弃不存在路径；Agent-3 单票校验失败 → `other_blocked`；`oversized` 仅绝对阈值；CLI 失败也写 `--out-dir` |
| 2026-11-06 | **Agent-1 移出 LangGraph**：父图仅 `validate_batch→agent2→agent3`；入参改为 `defectBatch` / `--defect-batch`；Agent-1 走 skill + `prepare-batch` |
| 2026-11-07 | **S2c**：Agent-2 形态化架构探测、匹配 A3/A4 置信度、`skills/code-cartography/` |
| 2026-11-08 | **S6**：Agent-2/3 可注入仓特异性 skill（`profiles: cartography` / `analyze` / `bugfix`）；overlay 优先于包内置；产物 `boundSkills[]` |
| 2026-11-09 | **拆包**：`contracts/` / `agent1/` / `platform/` 三个目录；skill 随产品切开；CLI 拆成 `bugfix-agent` 与 `bugfix-platform` |
