# Agent-1 探讨：缺陷批次准备（拉取 / 筛选 / 分簇）

> 日期：2026-10-30  
> **最近修订：2026-11-01 23:24（Asia/Shanghai）**  
> 状态：**Agent-1 探讨已收口**（非正式规格；实现前细节见文末）  
> 索引：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)  
> 漏斗细则：[缺陷单多轮筛选与分簇设计](2026-10-30-defect-screen-cluster-design.md)  
> 下游：[Agent-2](2026-10-30-agent2-code-cartographer-discussion.md) · [Agent-3](2026-10-30-agent3-defect-analyst-discussion.md)

---

## 0. 结论

| 项 | 决定 |
|---|---|
| 能力边界 | 拉取 + 蒸馏 + 规则筛选 + 三层分簇 + 排序 |
| 运行时 | **`defect-batch-prepare` Skill + 规则管线**；**不作**独立长会话 Agent |
| 拉取 | **纳入**；`mcp` 为准、`crawler` 为备；经 `raw-defects` 与后续**解耦** |
| 分簇 | L1 测试模块 → L2 标题括注 → L3 AI 意图；筛池纯规则 |
| 产出 | `defect-batch` → Agent-2 / Agent-3 |
| 业务 Skill | **允许注入**（`profiles: defect-batch` 等）；指导模块别名、话术、线别规则说明——**不替代**筛池硬规则 |
| 对外耦合 | **仅** `defect-batch`（及内部 `raw-defects`）；工作流松耦合，见[索引](2026-10-30-three-agent-architecture-discussion.md) |
| I/O 校验 | 输出后固定脚本校验 `defect-batch`；下游输入前再校验——失败不交给 Agent-2/3 |

---

## 1. 职责

| 做 | 不做 |
|---|---|
| **拉取**（§2，与后续解耦） | 通读业务源码 |
| 蒸馏描述模板、清洗、模块/标题括注取值 | 根因与改码 |
| 规则硬分流（CVE / 端侧 / 偶现 / 信息过薄等） | 缺陷平台**写**操作（关单等） |
| 三层分簇 + 排序 | 把筛池规则交给模型自由发挥 |

---

## 2. 拉取：纳入范围，与后续步骤分开

| 项 | 约定 |
|---|---|
| 是否纳入 | **是**（「缺陷批次准备」能力边界） |
| 形态 | `mcp`（**当前为准**）/ `crawler`（备）/ `preloaded` |
| 解耦 | 独立 **Ingest**，唯一产物 `raw-defects`；蒸馏/筛选/分簇**只读该产物** |
| 切换 | MCP 不可用可降级 crawler/预置文件，不改下游契约 |
| 凭据 | 环境变量 / MCP 配置；不进缺陷正文、不进 skill 正文 |

```text
IngestAdapter.mcp      ──┐
IngestAdapter.crawler  ──┼──► raw-defects ──► 蒸馏 → 筛选 → 分簇 → defect-batch
preloaded file         ──┘         ▲
                                   │ 下游禁止绕过此边界回查平台
```

Orchestrator **确定性调用** MCP 白名单拉单；Skill 可写用法与字段映射，拉全与落盘由适配器保证。

---

## 3. 分簇层次

- **L1** `测试模块`（规则归一；禁用 `所属模块`）  
- **L2** 标题 `【】` / `[]`（规则；无则 `_untagged`）  
- **L3** 缺陷意图（**AI**；表字段 `type` 仅先验）  

筛池（R0–R3）不含 AI。权威漏斗语义见 [筛选分簇设计](2026-10-30-defect-screen-cluster-design.md)。

---

## 4. 处理流程（端到端）

```text
【输入】productLine / α|β / ingest（mcp|crawler|preloaded）/ 可选 intent 配置
        │
        ▼
┌─ I. Ingest（与后续解耦）─────────────────────────────┐
│  MCP（准）| 爬虫（备）| 预置文件 → raw-defects         │
└──────────────────────────┬────────────────────────────┘
                           ▼
┌─ A. 蒸馏（0 LLM）─────────────────────────────────────┐
│  模板拆解；清洗；模块/标题括注；duplicate              │
└──────────────────────────┬────────────────────────────┘
                           ▼
┌─ B. 筛选漏斗（纯规则）────────────────────────────────┐
│  R0→R1→R2→R3a/b → strict | 旁路池                      │
└──────────────────────────┬────────────────────────────┘
                           ▼ 仅 strict 进分簇
┌─ C. 三层分簇 ─────────────────────────────────────────┐
│  L1/L2 规则 → L3 AI 意图 → R5 兜底 → R6 排序           │
└──────────────────────────┬────────────────────────────┘
                           ▼
【输出 · defect-batch】→ Agent-2 / Agent-3
  （旁路池仍可进 batch；Agent-2 默认还匹配 locatable_only / needs_info，见 Agent-2 C1）
```

| 阶段 | LLM？ | 产物要点 |
|---|---|---|
| I Ingest | 否（I/O） | `raw-defects` |
| A 蒸馏 | 否 | `DefectDigest` |
| B 筛选 | 否 | `pool` / `reasonCode` / `expectQuality` |
| C L1–L2 | 否 | `testModule` / `titleTag` |
| C L3 | **是** | `intent` / `intentSource` / `intentConfidence` |
| C R5–R6 | 否 | 终态簇 + 优先级 |

---

## 5. 形态：Skill + 管线（非独立 Agent）

| 步骤 | 本质 | 载体 |
|---|---|---|
| Ingest | I/O | `IngestAdapter` + MCP；Skill 写用法 |
| 蒸馏 / R0–R3 / L1–L2 / R5–R6 | 可复算规则 | **代码管线** |
| L3 意图 | 短推理 | 管线内批处理 LLM |

不必单独长会话 Agent：主路径 0 LLM；拉取已有 MCP；与「Skills = 知识、MCP = 工具、Orchestrator = 门禁」一致。

```text
defect-batch-prepare/SKILL.md
src/ingest/{mcp,crawler}.ts
src/pipeline/{distill,screen,cluster-*}
→ defect-batch.json
```

### 5.1 业务特性 Skill 注入

与索引「三端均可注入」一致。本段典型用途：

- 产品线模块名 / 测试模块别名 → L1 归一提示  
- 标题括注习惯、缺陷描述模板变体 → 蒸馏与 L2  
- 意图类目业务释义 → L3（仍受封闭枚举约束）  
- **不可**：用 skill 推翻 R2 硬淘汰或绕过 `raw-defects` 边界  

注入入口：Run `options.skills` / `.bugfix/skills` / 仓内 `.claude/skills`（merge；`profiles` 含 `defect-batch`）。

---

## 6. 拍板与遗留

- [x] 拉取纳入；MCP 准 / 爬虫备；`raw-defects` 解耦  
- [x] 分簇 L1→L2→L3；筛池纯规则  
- [x] Skill + 规则管线（2026-11-01 确认）  
- [x] 允许用户注入业务特性 Skill（不替代硬规则）  
- [x] 作为工作流独立单元；对外只约定 `defect-batch` + 进出脚本校验  
- [ ] L3 意图封闭枚举终版  
- [ ] MCP 工具名 / 字段映射契约（按实际缺陷 MCP）  
- [ ] `defect-batch` schemaVersion 终版（跨段 Q-D）  

与现有代码：`pipeline/normalize` + `aggregate` 可为规则层演进基础；`filterSkills` / `mountSkillsIntoCwd` 需支持分段 profile + merge。

---

## 7. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出 |
| 2026-11-01 | 分簇 / 拉取 / Skill+管线收口（合稿内已确认） |
| 2026-11-01 | 明确业务特性 Skill 可注入 |
| 2026-11-01 | 松耦合工作流；defect-batch 进出校验 |
| 2026-11-01 23:24 Asia/Shanghai | 时间戳标注；随三 Agent 探讨 PR 同步 |
