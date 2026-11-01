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
| 输入 | `defect-batch`（含蒸馏正文）+ `code-knowledge`（只传 artifact；**按条取用**） |
| 执行粒度 | **一条缺陷一个修复会话**；不整批同上下文改码。并发上限以 **git worktree**（或等价隔离目录）多开，各自只抽该条所需 batch/knowledge 切片 |
| 分析三层 | 定位 → 根因 → 修复方案（+验证；是否当场执行待拍，与 Agent-2 `runtimeVerify` 口子可对齐） |
| 产出 | 分析报告 +（探讨方向）按条改码/交付结果；对外 JSON 终版不急 |
| 产品边界 | **相对 10-23 放宽**：不只「止于报告」——Agent-3 承担按条修复；报告仍要双结局说明 |
| 运行时 | 倾向 LangGraph + Claude Agent SDK（待专题拍）；会话预算按条核算 |
| 业务 Skill | **允许注入**（`profiles: analyze` / fix）；指导根因习惯、验收、禁忌面、环境验证 |
| 对外耦合 | 契约 I/O；跨 Agent schema **不急冻** |

---

## 1. 三层分析 + 按条修复

1. **定位**（localization）——引用该条 `defectCodeMatches` + 模块/DR 切片（C9 方向）  
2. **根因**（rootCause）——证据链可核查；蒸馏正文（实际/期望/步骤）在本段按条注入（C8）  
3. **修复**（proposedFix → 改码；验证是否执行待拍）  

**并发模型（已倾向）**：串行为默认心智模型；要吞吐则 **每缺陷独立 worktree**，禁止多缺陷共享同一脏工作树/同一超长会话。

报告双形态仍保留；交接字段对齐 10-23 精神（`ruledOut` / `openQuestions` 等），schema 终版不急。

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
- [x] **按条修复**；并发用 worktree；蒸馏正文在本段按条取用（自 Agent-2 C8）  
- [ ] `analysis-report` / 修复结果 schema 终版（跨段 Q-D，**不急**）  
- [ ] 对外「可修/不可修」vs `confidence` + `suggestedAction`  
- [ ] 与 10-23 六段报告的字段差分；产品边界相对「止于报告」的正式表述  
- [ ] 运行时：LangGraph + SDK 是否与 Agent-2 同构；会话预算；worktree 编排细节  
- [ ] `defectCodeMatches`：强制起点 vs 参考；无候选时是否仍尝试修复  
- [ ] 验证：是否执行、与 Agent-2 `runtimeVerify` / 业务 skill 如何分工  

---

## 6. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出（合稿中本节较薄，待深化） |
| 2026-11-01 | 业务 Skill；松耦合工作流 |
| 2026-11-01 | **按条修复 + worktree 并发**；蒸馏正文归本段；相对 10-23「止于报告」放宽 |
