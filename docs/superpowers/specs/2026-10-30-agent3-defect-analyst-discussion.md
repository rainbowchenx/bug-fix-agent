# Agent-3 探讨：缺陷分析与报告

> 日期：2026-10-30（2026-11-01 拆出）  
> 状态：**探讨中**（非正式规格；内容少于 Agent-1/2，待专题深化）  
> 索引：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)  
> 上游：[Agent-1](2026-10-30-agent1-defect-batch-discussion.md) · [Agent-2](2026-10-30-agent2-code-cartographer-discussion.md)  
> 对齐：[报告型分析 Agent 设计](2026-10-23-report-agent-design.md)

---

## 0. 结论（当前）

| 项 | 倾向 |
|---|---|
| 输入 | `defect-batch` + `code-knowledge`（只传 artifact） |
| 分析三层 | 定位 → 根因 → 修复方案（验证方案设计，不执行） |
| 产出 | `analysis-report`（JSON + MD）；可行动 / 暂缓 / 非代码等说明 |
| 产品边界 | 与 10-23 一致：**止于分析报告**；改码 / MR 留给下游 |
| 运行时 | 真会话可能性最高（成本重心）；倾向与 Agent-2 同构（LangGraph + Claude Agent SDK，待拍） |
| 业务 Skill | **允许注入**（`profiles: analyze` 等）；指导业务根因习惯、验收口径、禁忌改动面 |
| 对外耦合 | **仅**消费已校验的 `defect-batch` + `code-knowledge`；产出已校验的 `analysis-report` |
| I/O 校验 | 输入前双校验；输出后校验 report；失败不交付下游 |

---

## 1. 三层分析

1. **定位**（localization）——强制引用 `code-knowledge`（含 `defectCodeMatches`）+ `scopeHint`  
2. **根因**（rootCause）——证据链可核查  
3. **修复方案**（proposedFix + 验证方案设计，**不执行**）  

报告双形态：机器 JSON + 人读 MD；交接字段保留 `ruledOut` / `openQuestions`（见 10-23）。

---

## 2. 「可修 / 不可修」语义

探讨张力：

- 用户表述：报告给出可修复与不可修复的详细说明。  
- 10-23：去掉 `fixability` gate，改为 `confidence` + `suggestedAction`，**不丢条、只路由**。

折中倾向（**未拍板**）：

| 对外说法 | 底层字段 |
|---|---|
| 建议改码 | `suggestedAction=code_fix` + confidence |
| 需补证 / 运行时 | `needs_runtime_info` / `needs_design_input` |
| 非代码 / 依赖配置 | `not_code` / `config_or_dependency` |

若必须保留「可修/不可修」文案，后两类可映射为「不可修复（原因码）」；证据纪律仍走可计算字段。

---

## 3. 业务特性 Skill 注入

与索引「三端均可注入」一致。本段典型用途：

- 业务域失败模式 / 常见根因话术  
- 哪些目录为公共 API、禁止大改  
- 验收与 `suggestedAction` 业务释义  
- 与 DR/DS 字段如何引用  

注入：Run / `.bugfix/skills` / 仓内 `.claude/skills`（merge；`profiles` 含 `analyze`）。  
Skill **不**取消证据链与路径存在性等可计算降级（对齐 10-23 `CONF-*` 精神）。

---

## 4. 与现有代码 / 文档

| 现有 | 关系 |
|---|---|
| `pipeline/analyze.ts` | 主干；需消费 `defect-batch` + `code-knowledge` |
| 10-23 报告契约 | 输出应对齐或显式差分 |

---

## 5. 待拍板

- [x] 允许用户注入业务特性 Skill（analyze profile）  
- [x] 工作流独立单元；I/O 仅契约 + 固定脚本校验  
- [ ] `analysis-report` schemaVersion 终版（跨段 Q-D）  
- [ ] 对外「可修/不可修」vs `confidence` + `suggestedAction`  
- [ ] 与 10-23 六段报告的字段差分表  
- [ ] 运行时形态（LangGraph + SDK 是否与 Agent-2 同构；会话预算；按簇并发）  
- [ ] 如何消费 Agent-2 的 `defectCodeMatches`（强制起点 vs 参考）  

---

## 6. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出（合稿中本节较薄，待深化） |
| 2026-11-01 | 明确业务特性 Skill 可注入 |
| 2026-11-01 | 松耦合工作流；双输入与 report 进出校验 |
