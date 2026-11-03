# 三 Agent 正式架构（Python）

> 日期：2026-11-03  
> 状态：**实现中 · Python**  
> 探讨基线：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)

---

## 1. 目标

松耦合工作流；**实现语言为 Python**（`bugfix_agent/`），不再维护 JS 三 Agent 路径。

```text
validate → Agent-1 → validate → Agent-2 → validate → Agent-3 → validate
            defect-batch         code-knowledge        analysis-report
```

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
| `bugfix_agent/agents/analyst/` | Agent-3 | 按条路由/报告 |
| `bugfix_agent/workflow/` | 父编排 | 串段 + 进出校验 |
| `bugfix_agent/cli.py` | CLI | `bugfix-agent run` |

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
| S1 | Agent-1 规则管线 | ✅ |
| S2a | Agent-2 detect/match | ✅ |
| S3a | Agent-3 outcome 路由 | ✅ |
| S2b/S3b | LLM/SDK 会话 | 后续 |
| S4 | HTTP 服务（可选 FastAPI） | 后续 |

---

## 修订记录

| 日期 | 说明 |
|---|---|
| 2026-11-03 | 脚手架（曾用 TS） |
| 2026-11-03 | **切换为 Python 实现**；移除 JS 三 Agent 代码 |
