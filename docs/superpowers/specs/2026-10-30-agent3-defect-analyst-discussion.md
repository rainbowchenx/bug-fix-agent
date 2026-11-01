# Agent-3 探讨：缺陷分析与按条修复

> 日期：2026-10-30（2026-11-01 专题深化）  
> 状态：**探讨中**（非正式规格）  
> 索引：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)  
> 上游：[Agent-1](2026-10-30-agent1-defect-batch-discussion.md) · [Agent-2](2026-10-30-agent2-code-cartographer-discussion.md)  
> 对照：[报告型分析 Agent 设计](2026-10-23-report-agent-design.md)（10-23）· [本地 BugFix 设计](2026-10-14-local-bugfix-agent-design.md)（10-14）

---

## 0. 结论（当前倾向）

| 项 | 倾向 |
|---|---|
| 职责 | **按条**：定位 → 根因 →（可行动则）改码/验证/交付说明；不可行动写清原因。汇总双结局报告 |
| 输入 | `defect-batch`（含蒸馏正文）+ `code-knowledge`；**只传 artifact**；按条切片进会话 |
| 粒度 | **一条缺陷一个修复会话**；禁止整批同上下文改码。并发：独立 **worktree**（或等价隔离目录） |
| 相对 10-23 | **产品边界放宽**：Agent-3 **做修复**，不只出报告；仍保留 10-23 的路由/举证纪律（`confidence` / `suggestedAction` / `ruledOut` / `openQuestions`） |
| 相对 10-14 | 对齐「全自动、双结局、无中间等人」；**GREEN 门禁精神保留**（验证不过 → 记 unfixed，不伪造成功交付） |
| 运行时 | **LangGraph（批编排 + 按条子图）+ Claude Agent SDK**（与 Agent-2 同构）；Skill/MCP 附着 |
| 业务 Skill | 可注入（`profiles: analyze` / `fix` / `verify`） |
| 对外耦合 | 松耦合契约 I/O；**JSON 终版不急**（Q-D） |
| 验证口子 | **Agent-3 主责**按条验证；与 Agent-2 `runtimeVerify`（通读期可选探测）分工见 §5 |

---

## 1. 与 10-23 / 10-14 的关系

| 来源 | 采纳 | 废弃 / 放宽 |
|---|---|---|
| 10-23 | 不丢条只路由；`confidence`+`suggestedAction`；`ruledOut`/`openQuestions`；证据降级纪律；JSON+MD 双形态 | **BOUND-1「只分析不出码」**——本三 Agent 探讨下由 Agent-3 承担按条修复 |
| 10-14 | 全自动闭环；双结局（fixed / unfixed）；没有 GREEN 不交付成功态；按隔离工作区改码 | 「一簇一 MR」可改为 **一条一交付单元**（簇仅作报告分组）；具体 MR 策略见 §8 D 组 |

对外仍可说「可修 / 不可修」**文案**，底层建议映射到 `suggestedAction` + 结局桶，避免重新发明 fixability gate。

---

## 2. 端到端流程（按条）

```text
【输入】已校验 defect-batch + code-knowledge
        │
        ▼
┌─ batch_orchestrator（LangGraph）──────────────────────────┐
│  展开待处理票（池对齐 Agent-2 C1：strict+locatable+needs_info 等）│
│  串行 或 有限并发（每票独立 worktree）                         │
└──────────────────────────┬────────────────────────────────┘
                           ▼  per defectId
┌─ ticket_subgraph ─────────────────────────────────────────┐
│  1. slice     抽该条 digest + matches + 相关 modules/DR     │
│  2. localize  以 defectCodeMatches 为起点（可扩展检索）      │
│  3. rootCause 证据链；写 ruledOut / openQuestions           │
│  4. route     confidence + suggestedAction                  │
│     ├─ 非 code_fix → 记 unfixed（原因码）→ 结束该条      │
│     └─ code_fix →                                        │
│  5. implement SDK 改码（minimal-diff / 业务 skill）          │
│  6. verify    按 profile / 注入 skill 跑验证（§5）           │
│     ├─ GREEN → deliver（push/MR 或仅本地结果，见 D 组）     │
│     │          → fixed                                      │
│     └─ RED / 预算耗尽 → iterate? → 仍失败 → unfixed         │
└──────────────────────────┬────────────────────────────────┘
                           ▼
【输出】analysis-report（JSON + MD）：fixed[] + unfixed[] + 汇总
         （schema 终版不急；进出仍做「有则校验」）
```

原则：

1. **一事一会话**：每票独立 SDK 上下文；不把其它票的 diff/对话带进来。  
2. **切片而非灌仓**：只注入该条需要的 batch 字段 + knowledge 相关片段。  
3. **全自动**：route / 失败后不等人；写清原因进报告。  
4. **松耦合**：不回调 Agent-1/2 内部；缺知识就在本段降级检索并记 `partial`/`openQuestions`。

---

## 3. 运行时形状

与 Agent-2 同构，但节点不同：

| 层 | 职责 |
|---|---|
| 父工作流 | validate(batch, knowledge) → 调 Agent-3 单元 → validate(report) |
| Agent-3 LangGraph | `batch_orchestrator`：调度票、worktree 生命周期、汇总 |
| `ticket_subgraph` | slice → localize → rootCause → route →（可选）implement → verify → deliver → emit |
| Claude Agent SDK | 探索/改码会话；挂载 analyze/fix/verify skills + MCP |
| 确定性代码 | worktree 创建/回收、验证命令执行、schema 校验、结局归桶 |

**不宜**学 Agent-1 做成纯 Skill+管线：本段是探索+改码+验证环，必须有 SDK 会话。

---

## 4. 双结局与「可修」语义

### 4.1 报告桶（对外）

| 桶 | 含义 |
|---|---|
| `fixed[]` | 已改码且验证通过（及可选已开 MR）；含证据摘要、`mrUrl?` |
| `unfixed[]` | 未改或未通过；含 `reasonCode` + `reasonDetail` + 已做分析（定位/根因/方案草稿） |

### 4.2 路由（对内，对齐 10-23）

| `suggestedAction` | 默认进哪一桶 |
|---|---|
| `code_fix` | 尝试 implement；成功→fixed，失败→unfixed |
| `needs_runtime_info` / `needs_design_input` | 默认 **不改码** → unfixed（原因=需补证/需设计） |
| `config_or_dependency` / `not_code` | 默认不改码 → unfixed |

> 若产品坚持口头「可修复/不可修复」：`fixed` ∪（尝试过 code_fix 但失败）可再分子类；**路由标签仍保留**，避免只剩自然语言。

### 4.3 硬门禁（建议默认，待 D 组确认）

- **没有 GREEN，不进 `fixed`**，也不宣称交付成功。  
- 验证跳过（环境不可用）→ 不得冒充 GREEN；记 `unfixed` 或单独 `fixed_unverified`（**是否允许后者见 D5**）。

---

## 5. 验证分工（相对 Agent-2 `runtimeVerify`）

| 能力 | Agent-2 | Agent-3 |
|---|---|---|
| 目的 | 通读期可选：摸清如何起环境（默认 **off**） | **修复后验收**（主路径） |
| 开关 | `runtimeVerify` | 建议 `verifyMode`: `off` \| `commands` \| `skill_guided`（默认倾向 `commands` 或 profile 探测） |
| Skill | 可注「环境怎么起」 | 可注「怎么验这条/这个业务」 |
| 失败影响 | 最多 `partial` knowledge | 直接影响 fixed/unfixed |

Agent-2 若已写出环境笔记到 `code-knowledge`（可选字段，终版不急），Agent-3 verify 应优先消费，避免重复摸索。

---

## 6. `defectCodeMatches` 用法

| 策略 | 说明 | 建议 |
|---|---|---|
| 强制起点 | 无候选则不改码 | 过严（C1 旁路票可能无强匹配） |
| 仅参考 | 可完全忽略 matches | 浪费 Agent-2 |
| **软起点（推荐）** | 有候选→优先；空/低置信→本段可降级 Glob/Grep/CodeGraph 再搜；仍无则 `suggestedAction` 倾向 needs_* 或 unfixed | **默认** |

---

## 7. 业务 Skill 注入

`profiles` 建议：`analyze` | `fix` | `verify`（可多选）。

典型：

- 业务根因话术 / 禁忌改动目录  
- 微前端子应用对照、Electron IPC 边界、设备 JSBridge  
- 验收命令、账号、固件/实机限制  
- MR 标题/描述模板  

不取消：路径存在性检查、GREEN 纪律、schema 校验。

---

## 8. 拍板清单（本轮请逐组表态）

### 8.1 已确认（来自既有探讨）

- [x] 松耦合；只传 artifact；不共享跨 Agent 会话  
- [x] 业务 Skill 可注入  
- [x] **按条修复**；并发用 worktree；蒸馏正文本段按条取用  
- [x] 跨 Agent JSON 终版不急  

### 8.2 D 组——建议本轮就拍

| ID | 问题 | 建议默认 |
|---|---|---|
| **D1** | 相对 10-23：Agent-3 **是否正式承担改码** | **是**（本探讨主路径）；10-23 BOUND-1 对本工作流不适用 |
| **D2** | 对外「可修/不可修」vs 路由字段 | **双轨**：报告桶 fixed/unfixed + 内层 `suggestedAction`/`confidence`；不恢复 fixability gate |
| **D3** | 无 GREEN 能否进 fixed | **否**（对齐 10-14） |
| **D4** | `defectCodeMatches` | **软起点**（§6） |
| **D5** | 验证环境缺失时 | **不得** `fixed`；记 unfixed/`verify_unavailable`；不发明 `fixed_unverified`（一期） |
| **D6** | 交付形态 | 默认：**可开 MR**（有凭据时）；无凭据则本地 branch + 报告链到路径；不自动 merge |
| **D7** | 一票一 MR 还是可合并 | 默认 **一票一 MR**（与按条隔离一致）；同簇合并以后再开 |
| **D8** | 运行时 | 确认 **LangGraph + Claude Agent SDK** |
| **D9** | 批内并发度 | 默认串行；`maxParallelWorktrees` 可配（建议默认 1~3） |
| **D10** | 迭代预算 | 默认 `maxIterate=3`（对齐旧管线精神） |

### 8.3 E 组——可延后

| ID | 问题 |
|---|---|
| **E1** | report / 单票结果 JSON 终版（Q-D） |
| **E2** | 与 10-23 六段报告字段差分表 |
| **E3** | worktree 在「多子仓 workDir」下的路径约定 |
| **E4** | 安全旁路票是否进入 Agent-3 |
| **E5** | 实机/设备 web 验证的专用 skill 样例 |

---

## 9. 与现有代码

| 现有 | 关系 |
|---|---|
| `pipeline/analyze.ts` / `implement` / `verify` / `deliver` | 逻辑可迁入 Agent-3 单元，但编排改为按条 + worktree |
| `src/graph/*` + `sdk-runner.ts` | 复用挂载；Agent-3 **独立子图**，勿与 Cartographer 状态混用 |
| 10-23 报告渲染 | 可作 MD/JSON 骨架，叠加 fixed/unfixed |

---

## 10. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出（较薄） |
| 2026-11-01 | 业务 Skill；松耦合；按条修复 + worktree；相对止于报告放宽 |
| 2026-11-01 | **专题深化**：流程/运行时/双结局/验证分工/matches 软起点；D/E 拍板清单 |
