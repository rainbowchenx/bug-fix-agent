# 报告型分析 Agent：决策跟进分析

> 基线：`main` @ `e01cc6a`（2026-10-29）。
> 前置：[落地前决策备忘](2026-10-23-report-agent-decision-memo.md)（`Q-*` / `U-*` / `J-*` / `R-*`）、[报告型分析 Agent 设计](2026-10-23-report-agent-design.md)。
> 触发：产品负责人对备忘录给出四条方向性答复（见 §1）。本文**闭合已答项、推演架构冲击、列出由此新开的问题**。不含实现。
> 编号：沿用备忘录；新增 `ANS-*`（已确认答复）、`IMP-*`（冲击）、`NQ-*`（由此新开的问题）。

---

## 0. 结论先行

| 项 | 内容 |
|---|---|
| 技术栈定性 | **整仓转向 Python**：编排 = LangGraph（Python）；节点内 LLM = `claude-agent-sdk`（Claude Code 子进程）。现有 TypeScript/`@langchain/langgraph` JS 实现**不再演进，按退役处理** |
| 不是"改引擎开关" | 这是**重写**，不是把 `options.engine` 默认值改成 `langgraph`。TS 里的 `src/graph/`（约 885 行）与 `src/pipeline/*` 修复侧一并作废；可迁移的是**算法与契约**（蒸馏规则、置信度、报告 schema），不是源码行 |
| SWE | **整枝删除**：`adapters/swe-bench/`、`eval/swe/`、相关 npm scripts、测试、设计文档。报告型 Agent 不以 patch 命中率为目标 |
| 缺陷输入 | 生产路径 = **业务侧 MCP**（用户身份 + 项目编号 → open/new + 附件）；过渡期 = **手动导出 xlsx**（仓库内 `缺陷列表demo/`）。两者共用同一 `Defect` / `DefectDigest` 契约 |
| 版本 tag | **非保证信号**。`LOC-S1` 有则用、无则跳过；`scopeHint` 必须在"零 tag"下仍可工作，且**不得仅因缺 tag 把 confidence 压到 low** |
| 最大风险 | ① 语言栈切换期间双轨维护成本；② MCP 工具 schema 尚未到手，蒸馏层先按 xlsx 定型；③ Claude Agent SDK 子进程模型对并发与资源的约束（每会话一 CLI 进程） |

---

## 1. 已确认答复（`ANS-*`）

| 备忘编号 | 答复 | 落定结论 |
|---|---|---|
| `Q-7` | 全量使用 **LangGraph Python**；底层依旧 **Claude Code** | 闭合为：唯一编排引擎 = `langgraph`（Python）；唯一 LLM 执行面 = `claude-agent-sdk`（Python，内部拉起 Claude Code CLI）。**退役**：TS `pipeline` 引擎、TS `langgraph` 引擎、`@langchain/langgraph` JS 依赖、`langgraph.json`（Node 版） |
| `Q-8` | 去除 SWE 相关东西 | 闭合为选项 **A 全退役**（不再走"改造成定位评测"）。定位评测另找真值源（见 `NQ-6`） |
| `U-5` 部分 | 业务侧会提供 MCP，按用户 + 项目编号拉缺陷；分析阶段暂用手动导出文件 | 闭合为双适配器：`McpDefectSource`（生产）+ `XlsxDefectSource`（过渡）。当前实现与联调以 xlsx 为准 |
| `U-4` / `DEC-17` | 目标仓库版本 tag **不一定有**，各业务线不一致 | 闭合为：`LOC-S1` 为**可选信号**；`scopeHint` 对缺 tag 必须有退化路径；缺 tag ≠ 证据不足 |

> 备忘录中其余默认项（`Q-1`/`Q-2`/`Q-4`/`Q-3`/`Q-5`/`Q-6`/`Q-9`/`Q-10`）本次未改口，仍按原默认执行，除非后续另答。

---

## 2. 架构冲击（`IMP-*`）

### IMP-1 分层不变，实现语言全换

正确分工（与 Claude Agent SDK 官方 hosting 模型一致）：

```
┌─────────────────────────────────────────────────────────┐
│  LangGraph（Python）—— 外层骨架                         │
│  状态机 / 路由 / checkpoint / 并发闸门 / 产物落盘         │
│                                                         │
│  节点多为纯 Python（0 LLM）：                            │
│    ingest → distill → prefilter → dedupe → aggregate    │
│    → scope_hint → confidence → render                   │
│                                                         │
│  唯一重 LLM 节点：analyze                               │
│    └─ 调用 claude-agent-sdk.query(...)                  │
│         └─ 子进程：Claude Code CLI                      │
│              工具：Read / Glob / Grep（只读）            │
│              + 可选 MCP（业务缺陷 MCP 一般不在此调用）   │
└─────────────────────────────────────────────────────────┘
```

**不要**把"拉缺陷 / 蒸馏 / 分簇 / 置信度"放进 Claude 会话里烧 turn——这些是确定性逻辑，放 LangGraph 节点里更便宜、可测、可重放。Claude 会话只做：在 `scopeHint` 内读代码 → 产出 6 段结构化分析。

### IMP-2 现有 TypeScript 仓的命运

| 资产 | 处理 |
|---|---|
| `src/pipeline/{analyze,aggregate,normalize,repo-map,report,localization,failure-modes}.ts` | **算法迁移**：规则与 schema 用 Python 重写；不 `subprocess` 调旧 TS |
| `src/pipeline/{implement,verify,deliver,review,baseline,static-check,scope-lock,prepare,fixability}.ts` | **删除**（修复侧，报告型边界下本就退役） |
| `src/graph/*`、`langgraph.json`、`docs/langgraph.md` | **删除**（JS LangGraph）；用 Python 版图与文档替换 |
| `src/agent/sdk-runner.ts` | **语义迁移**到 `claude_agent_sdk.ClaudeAgentOptions` + `query()` |
| `src/http/app.ts`（Hono） | **替换**：优先 LangGraph Server 原生 HTTP；若 Dify 仍要 `POST /v1/runs` 兼容壳，用 FastAPI 薄封装（见 `NQ-2`） |
| `src/mcp/load-config.ts` | **迁移**：Python 侧合并 run 级 / 本机 MCP 配置，注入 SDK 或 ingest 节点 |
| `skills/` | **保留目录形态**（Claude Code skill 是语言无关的 markdown）；去掉修复侧 5 个（`verify-green-gate` / `reproduction-test` / `gitlab-mr-hygiene` / `patch-review` / `minimal-diff`） |
| `adapters/swe-bench/`、`eval/swe/`、`docs/.../2026-10-18-swe-bench-adapter-design.md`、`test/unit/swe-adapter.test.ts`、`package.json` 的 `swe:*` scripts | **整枝删除** |
| `缺陷列表demo/*.xlsx` | **保留**，作为 `XlsxDefectSource` 的回归样本 |
| `package.json` / npm 发布 | 随 Python 化 **停止作为主交付物**；是否保留空壳或改发 PyPI 见 `NQ-1` |

### IMP-3 Claude Agent SDK（Python）要点

官方包：`claude-agent-sdk`（PyPI；原名 `claude-code-sdk`）。关键约束：

| 点 | 含义 |
|---|---|
| 子进程模型 | 每次 `query()` 拉起一个 Claude Code CLI；N 并发分析 = N 个 CLI 进程 + 各自 transcript |
| `cwd` | 必须指向目标仓库（只读分析）；多仓时每仓独立会话或同会话多根（优先每仓一 cwd） |
| 工具白名单 | analyze 节点：`allowed_tools=["Read","Glob","Grep"]`（+ Skill）；**禁止** Edit/Write/Bash |
| Hooks | `PreToolUse` 可实现 `LOC-R`（Grep 限制在 `scopeHint` 内；`scopeHint` 为空则不拦截） |
| MCP | SDK 原生支持 `mcp_servers`；缺陷拉取 MCP **建议在 LangGraph ingest 节点调用**，不塞进 analyze 会话（省 turn、结果可缓存、可单测） |
| 凭据 | `ANTHROPIC_API_KEY` 等走环境变量；缺陷平台凭据留在业务 MCP 进程内，本产品不落明文 |

### IMP-4 缺陷输入双适配器

```
                    ┌─ XlsxDefectSource ────────┐
Run 请求 ──────────┤  (过渡期 / 本地联调)        ├──→ Defect[] → distill → …
  projectId         │  读 缺陷列表demo/*.xlsx    │
  userId?           ├─ McpDefectSource ─────────┤
  workDir           │  (生产)                    │
                    │  MCP: list_open_defects    │
                    │       get_attachments      │
                    └───────────────────────────┘
```

契约对齐 10-22 输入文档：

- 过滤：`缺陷状态 ∈ {Open, New}`（xlsx 侧我们做；MCP 侧约定由服务端滤好，客户端再断言一次）
- 身份：用户 + 项目编号只传给 MCP；xlsx 模式忽略身份
- 附件：MCP 落地到 `{runDir}/attachments/{defectId}/`；xlsx 模式 `attachments=[]` + `attachmentsUnavailable=true`
- **Agent 不持有缺陷平台凭据**（`INV-5` 仍成立）——凭据在 MCP server

过渡期验收标准：用 `配套-交通项目.xlsx` + `hcp巡检.xlsx` 能跑通 `ingest → distill → prefilter → aggregate`，产出与备忘录蒸馏回归集一致。

### IMP-5 版本 tag 可选 → `scopeHint` 必须可空

四信号改为**尽最大努力并集**：

| 信号 | 缺省时 |
|---|---|
| `LOC-S1` 版本 tag diff | **跳过**；在 `scopeHint.signals.used` 记 `tag_diff: false` |
| `LOC-S2` 申请时间窗 `git log` | 有 `reportedAt` 才用；xlsx 样本 30/30 有值，优先依赖 |
| `LOC-S3` 引入活动=编码 | 有则加权，无则忽略 |
| `LOC-S4` 模块 → 目录 | 依赖 `EnvironmentProfile.localization.moduleMapping`；无 mapping 时退回标题 `[]` 前缀启发式 |

硬性规则：

1. `scopeHint.files/dirs` 可以为空。
2. 空 `scopeHint` → `LOC-R` **不拦截**（允许全仓 Grep）；`handoff.evidenceGaps` 加 `scope_hint_unavailable`。
3. **禁止**新增 `CONF-tag-missing` 之类规则把缺 tag 直接打成 low。缺 tag 只影响定位噪声，不是证据链断裂。
4. 报告 `localization.scopeHintHit.inVersionDiff` 在未跑 S1 时为 `null`（三态），不要写成 `false` 冒充"查过但不在 diff 内"。

### IMP-6 流水线收敛后的 Python 图（目标形状）

```
START
  → ingest          # Xlsx | MCP → Defect[]
  → distill         # 模板拆解 / 清洗 / module / descriptionTooThin
  → prefilter       # CLS + suggestedAction 初判（规则）
  → dedupe_aggregate# 去重 → 分簇 → 优先级
  → scope_hint      # 尽最大努力；可空
  → analyze_cluster # ★ 唯一 Claude Code 会话（可 fan-out）
  → confidence      # CONF-1..7 纯函数回写
  → render          # analysis-report.json + .md + 每簇 detail
END
```

对比旧 TS cluster 子图（`ensure_repo → analyze → prepare → implement → … → deliver`）：回边全部消失；并发从"抢 worktree/端口"变成"N 个只读 analyze 会话"，但仍受 CLI 进程数与 API 限流约束。

---

## 3. 对原落地顺序的修订（相对备忘录 `R-1`）

```
① 仓形态与契约（先定语言边界）
   pyproject.toml / 包结构 / AnalysisReport pydantic（或 dataclasses+jsonschema）
   删除 SWE 整枝；CLAUDE.md / README 按报告型 + Python 重写
   ↓
② 0 LLM 节点（可用 xlsx 回归，不依赖 Claude）
   distill / prefilter / dedupe / aggregate / confidence
   XlsxDefectSource
   ↓
③ scope_hint（git 只读；显式处理无 tag）
   + repo_map（i18n / 路由索引）
   ↓
④ LangGraph 骨架（尚无 LLM）
   串起 ②③ → render 空壳；用 fixture 跑通状态与落盘
   ↓
⑤ analyze 节点接 claude-agent-sdk
   只读工具 + LOC-R hook + 6 段产物解析
   ↓
⑥ McpDefectSource 适配（等业务 MCP schema）
   ingest 切换；xlsx 保留为 fallback / 测试
   ↓
⑦ 退役 TS 树（或归档到 archive/ 后删）
```

与备忘录 `R-1` 的差异：把"语言栈切换 + SWE 删除"提前到第 ① 步；把 MCP 接到有 schema 之后；评测真值不再指望 SWE（见 `NQ-6`）。

---

## 4. 由此新开的问题（`NQ-*`）——需要你再拍或补充

| # | 问题 | 为什么现在才问 | 建议默认 |
|---|---|---|---|
| `NQ-1` | **交付形态**：PyPI 包？仅内部 Git + `uv run`？是否保留空 npm 包避免下游断链？ | 整仓转 Python 后 npm `bugfix-agent` 无主交付意义 | 新 Python 包（名另定）+ 停发 npm；Dify 侧改调 LangGraph Server / FastAPI |
| `NQ-2` | **对外 HTTP**：只用 LangGraph Server，还是再包一层 `POST /v1/runs` 兼容 Dify？ | 现 Hono API 是 Dify 集成面 | 若 Dify 短期不改：FastAPI 兼容壳；长期：LangGraph Server |
| `NQ-3` | **业务缺陷 MCP 的工具草案**何时可提供？（至少：`list_defects(user, projectId, statuses)`、`get_attachments(defectId)` 的入参/出参） | 决定 `McpDefectSource` 能否与 ② 并行，还是必须串在 ⑥ | 先锁 xlsx 契约；MCP 出参必须能 map 到同一 `Defect` |
| `NQ-4` | **目标代码仓如何交给 Agent**：仍是调用方准备好的本地 `workDir`？还是也经 MCP/配置拉取？ | 只读分析仍需代码在本地磁盘上供 Claude Code `cwd` | 维持 `workDir` 已是可读仓库（`C-1`）；多仓用 `repoSet` 路径列表 |
| `NQ-5` | **并发上限**：单机同时跑几个 Claude Code 子进程可接受？ | SDK = 一会话一进程；报告型可高并发，但机器内存/fd/API 限流是硬顶 | 先默认 3，配置化 |
| `NQ-6` | **去掉 SWE 后，定位准确率用什么真值评测？** | 备忘录 `Q-8-B` 作废 | 短中期：xlsx 样本中带"初步定位"/已 Solved 同源单（如 `BGA260060855`↔`BGA250766745`）人工标文件集；中期：业务侧回写实际改动文件 |
| `NQ-7` | **包/项目命名**：继续 `bugfix-agent` 还是改名（如 `defect-report-agent`）？ | `Q-10` 原默认不改名；语言栈都换了，改名成本相对变低 | 倾向改名，避免"还会开 MR"的误解；可另定 |
| `NQ-8` | **旧 TS 代码删除节奏**：立即删，还是 `archive/ts-legacy` 留一个 tag 再删？ | 重写期可能要对照算法 | 打 `legacy-ts` tag 后删主树，避免双轨 |

---

## 5. 风险与对策（本轮特有）

| 风险 | 表现 | 对策 |
|---|---|---|
| 重写期间能力真空 | TS 已不演进、Python 未就绪 | 按 §3 先交付 0 LLM 路径（xlsx→蒸馏→分簇→空报告骨架），再接 Claude |
| MCP schema 迟到 | ingest 只能走 xlsx | `Defect` 契约以 xlsx 蒸馏结果为准；MCP adapter 做字段映射，禁止 MCP 形状倒逼核心 |
| 无 tag 导致定位噪声 | Grep 命中过多 | 强化 `LOC-S2`（时间窗）+ `LOC-S4`（模块目录）+ i18n `LOC-L1`；报告如实标 `scope_hint_unavailable` |
| Claude CLI 孤儿进程 | 父进程被杀后 CLI 残留 | 按官方 hosting 建议做进程组清理；LangGraph 节点 `finally` 保证会话结束 |
| 误把缺陷 MCP 塞进 analyze | 浪费 turn、结果不可测 | 架构评审检查点：ingest 节点不得调用 `claude_agent_sdk` |
| 文档与代码双过时 | `CLAUDE.md` 仍写 GREEN/MR + TS | `Q-1` 与本次栈切换合并为一次文档大修 |

---

## 6. 决策状态总表（更新后）

| 编号 | 状态 | 结论 |
|---|---|---|
| `Q-7` | ✅ 已定 | LangGraph **Python** 全量；底层 Claude Code（`claude-agent-sdk`）；TS 双引擎退役 |
| `Q-8` | ✅ 已定 | SWE **全删**（不做评测改造） |
| `U-4` | ✅ 已定 | tag 可选；`scopeHint` 可空；缺 tag 不单独降 confidence |
| `U-5` | ✅ 部分已定 | 生产 = 业务 MCP；过渡 = 手动 xlsx |
| `Q-1`..`Q-6` / `Q-9` / `Q-10` | 仍按备忘默认 | 未改口 |
| `NQ-1`..`NQ-8` | ⏳ 待答 | 见 §4 |

---

## 7. 一句话理解

你要的产品形态是：**Python LangGraph 管流程，Claude Code 只在分析节点里只读啃代码，缺陷从业务 MCP（过渡期 xlsx）进，报告出，MR 永远不出；仓库有没有 tag 都不能成为跑不通的理由。** 当前 TS 仓是这份设计的算法与样本资产库，不是目标运行时。
