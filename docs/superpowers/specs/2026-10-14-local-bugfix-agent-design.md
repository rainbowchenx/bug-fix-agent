# 本地 BugFix Agent 设计（Dify 编排 / 无状态执行器）

> 状态：**已固化；MVP 实现计划已就绪**  
> 日期：2026-10-14  
> 相关调研：[`docs/research/2026-10-14-sota-bugfix-agent-survey.md`](../../research/2026-10-14-sota-bugfix-agent-survey.md)  
> Seer 深潜：[`docs/research/2026-10-14-sentry-seer-autofix-deep-dive.md`](../../research/2026-10-14-sentry-seer-autofix-deep-dive.md)  
> 实现计划：[`docs/superpowers/plans/2026-10-14-local-bugfix-agent-mvp.md`](../plans/2026-10-14-local-bugfix-agent-mvp.md)

## 1. 目标与非目标

### 1.1 目标

| #   | 内容                                                                                                                                                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1  | 作为**独立本地智能体**，以 **npm 包**分发（`bin` CLI + 可编程 API）；用户本机 `npm i -g` / `npx` 安装后由 Dify 串联调用                                                                                                                          |
| G2  | Dify 负责校验、拉取缺陷列表（多为 Excel 解析结果）、指定 `workDir`                                                                                                              |
| G3  | **一次传入整表**；Agent 内做归一化、**缺陷聚合**等前置处理                                                                                                                      |
| G4  | **一簇缺陷 → 一个 GitLab MR**                                                                                                                                                   |
| G5  | 在 `workDir` 下 clone、创建修复相关目录，**执行与代码以本地为主**；Agent **自身不做业务数据存储**（无内置缺陷库/结果库），但**允许调用外部接口**将状态/报告读写到远程或其他系统 |
| G6  | 质量优先：本地装依赖 + 跑验证；**没有 GREEN，就没有 MR**                                                                                                                        |
| G7  | 验证命令：**自动探测** + Dify `userPrompt` 指导覆盖                                                                                                                             |
| G8  | 底层改码引擎：`@anthropic-ai/claude-agent-sdk`；外层自研编排二次包装                                                                                                            |
| G9  | 交付：本机 GitLab Token **push + 创建 MR**（不自动 merge）                                                                                                                      |
| G10 | 语言生态一期：Vue / Node / TypeScript / JavaScript / Electron；**Stack Profile 可切换、可自动识别、可扩展**                                                                     |
| G11 | **内置业界优秀 Skills**（`SKILL.md` 包）；启动只注入目录元数据，**由模型按需选择性调用**；支持用户/仓级扩展与禁用 |
| G12 | **可配置 MCP**：支持本地/远程 MCP Server（stdio / HTTP / SSE 等）；Run 或本机配置挂载后，由模型在允许范围内调用 MCP 工具 |
| G13 | **全自动闭环、无中间等人断点**：判定可修则一路跑到 **开 MR**；不可修/修失败则仍产出**完整报告说明原因**；不在根因/方案后等待用户回复（对标 Seer 的 stopping_point 人机协作模式，本产品明确不做） |
| G14 | **日报式交付**：典型用法是每日自动拉缺陷 → 一整次 Run → 汇总报告（已修+`mrUrl` / 未修+原因）；报告是给用户看的主产物 |

### 1.2 非目标（一期）

- 在 Agent 进程内自建缺陷库 / 结果库 / 多租户 Redis 主存（**不等于禁止**对接远程存储 API）
- 自动 merge MR
- 全语言 Profile（Java/Go 等只留扩展点）
- 把 `git push` / 建 MR 完全交给模型自由 Bash
- 替换或绑定监控平台 Context Pack 微服务形态（可参考旧仓执行内核，产品形态不同）
- **产品级中间停止点**（如「只做到根因就停、等人点继续」）；内部仍可有阶段机，但对用户是一次跑完
- 根因分析后交互式追问用户再继续（全自动场景下禁止）

## 2. 角色边界

| 角色                 | 负责                                                                                           | 不负责                                                  |
| -------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **Dify**             | 校验、Excel→缺陷数组、选 `workDir`、传入 `userPrompt`、触发一次 Run、展示进度与报告            | 聚合逻辑、改代码、Git 操作                              |
| **BugFix Agent**     | 聚合、分簇、编排、探测验证、SDK 改码、GitLab 交付、写本地 run 报告；**可选**调用外部存储 API   | 自建业务数据库；不替代远程系统的主数据职责              |
| **本地磁盘**         | 代码、依赖、本次 run 工作副本与日志                                                            | —                                                       |
| **外部存储（可选）** | 由 Agent **调用对方接口** 保存/读取：run 元数据、簇结果、报告、进度、配置等（如远程 HTTP API） | Agent 不实现对方的存储引擎                              |
| **本机环境**         | `GITLAB_TOKEN`、可选远程 API 凭证等                                                            | Token 不进 Excel；凭据走环境变量/本机密钥，不进缺陷正文 |

## 3. 架构

```text
Dify（日批拉缺陷）──HTTP──► BugFix Agent（一次 Run 跑完，不等用户）
                            │
                            ├─ Ingest / Normalize / Aggregate → Clusters
                            ├─ Skills + MCP + Stack Profile
                            ├─ Per cluster（无中间等人；可修则直达 MR）:
                            │    Analyze（Localization→RootCause→Plan）
                            │    ├─ 不可修 / 不可行动 → 写入「未修复」完整说明 → 下一簇
                            │    └─ 可修 → Prepare→Implement→Verify→Iterate*
                            │              ├─ GREEN → push + create MR → 「已修复」
                            │              └─ 失败耗尽 → 「未修复」完整说明（含已做分析）
                            └─ 汇总 Report（已修列表+mrUrl / 未修列表+原因）→ Dify / 远程
```

- **Orchestrator**：阶段状态机、门禁、探测、install/test 执行、git/MR（确定性代码）
- **Claude Agent SDK**：Implement / Iterate 改码；`Skill` + 已配置的 **MCP 工具**
- **Stack Profile**：detect / install / test 插件
- **Skills**：打包进 Agent 发行物；懒加载（progressive disclosure），不整本灌进 system prompt
- **MCP**：用户/Dify/本机配置服务器列表；Agent **转发挂载到 SDK**，不自研 MCP 协议栈

推荐实现路径：**npm 包 + 本地 HTTP（Dify Custom Tool）**。

### 3.1 npm 包形态（可行且推荐）

| 出口 | 用途 |
|------|------|
| **CLI**（`package.json` → `bin`） | `bugfix-agent serve` 启 127.0.0.1 HTTP；`bugfix-agent run --work-dir ...` 单次批跑 |
| **库 API** | `import { createApp, startRun } from 'bugfix-agent'` 供脚本/测试嵌入 |
| **内置 assets** | `skills/**`、默认 profile 随包发布（`files` 字段打进 tarball） |

安装示例：

```bash
npm i -g bugfix-agent
# 或
npx bugfix-agent serve --port 8787
```

注意：依赖 `@anthropic-ai/claude-agent-sdk` 的 **optional 平台二进制**，安装勿 `--omit=optional`；Windows/macOS/Linux 需对应 optionalDependency 装上。

Dify：Custom Tool / HTTP 节点指向本机 `http://127.0.0.1:8787`（用户先起 `serve`，或由 Dify 前序 shell 节点拉起）。

## 4. 目录约定

```text
{workDir}/
  repos/<gitlabRepo>/                 # clone（可跨 run 复用）
  .bugfix-runs/{runId}/
    input.defects.json
    plan.clusters.json
    clusters/<clusterId>/
      root-cause.json
      solution.json
      verify.json
      agent.log
    report.json
```

原则：

- **默认**：本地 run 目录文件即状态，保证断网/离线可跑通主路径。
- **可选远程同步**：通过可插拔 `StorageAdapter`（HTTP 等）把 run 进度、`report.json`、簇结果 **上传/拉取** 到远程服务器或其他系统；远程失败不阻断已完成的本地修复与 MR（策略可配置：`best_effort` / `required`）。
- Agent **不是**数据存储地：不建表、不持有缺陷主库；远程侧的 schema 与生命周期由对方服务负责。

## 5. 运行模式：全自动双结局（相对 Seer 的关键差异）

> **与 Seer 不同**：Seer 用 `stopping_point`（只到根因/方案/改码）做**人机协作断点**。本产品是**日批全自动**——用户要的是「拉缺陷 → 智能体修完 → 一份报告」，**不在中途等人回复**。

| 结局 | 条件 | 交付 |
|------|------|------|
| **已修复** | 判定可修，且 Implement + Verify GREEN，成功开 MR | 报告中列出缺陷/簇 + **`mrUrl`** + 根因/验证摘要 |
| **未修复** | 判定不可修，或修码/验证/开 MR 失败耗尽 | 报告中列出缺陷/簇 + **完整原因说明**（含已完成的分析产物，若有） |

原则：

- **可修 ⇒ 默认目标就是开到 MR**（不再提供「只分析到根因就停」的产品选项）
- **不可修 / 修失败 ⇒ 仍必须写全报告**，不得静默跳过
- 内部阶段（Localization→…→Deliver）仅服务编排与质量，**对用户无「点继续」**
- Run 级进度可轮询（`GET /v1/runs/:id`），那是观察，不是审批门闩

## 6. 质量流水线与门禁

> 反哺来源：Agentless / Seer artifact / SWE-agent / Aider 等；**停止点语义按 §5 改造**。详见调研与 Seer 深潜报告。

| 阶段 | 产出 | 本簇如何收尾（不等用户） |
|------|------|--------------------------|
| Normalize / Aggregate | `clusters[]` | 无法聚合 → 单条成簇或记入未修复并说明 |
| Prepare (repo) | clone + Profile + install | 失败 → **未修复**（环境/依赖原因）+ 完整说明 |
| Localization / Scope（只读） | 嫌疑文件/符号/边界 | 空洞且无法继续 → **未修复**（定位失败） |
| Root Cause（只读） | 根因 artifact + fixability 三态 | `not_actionable` / `needs_more_context` → **未修复**（写清原因与已有分析）；`fixable` → 继续 |
| Solution Plan（只读） | 方案 + 验收标准 | 方案无法形成 → **未修复**；可修 → 继续 |
| Implement（SDK） | diff | 无变更 → 进入未修复或 Iterate 策略 |
| Static check / Verify | GREEN | 失败 → Iterate（上限内自动重试）；耗尽 → **未修复**（附日志摘要） |
| Reviewer（P1） | approve / request_changes | 不通过 → 自动 Iterate；耗尽 → **未修复** |
| Deliver | `mrUrl` | 成功 → **已修复**；push/MR API 失败 → **未修复**（保留本地分支说明可手工重试） |

硬约束：

- **可修路径必须尝试走到 MR**；不得在根因后空等
- 无有效验证命令 / 验证失败 → **不得开 MR**，记入未修复并写明缺什么（**测试真值 > 模型自评**）
- 分析阶段禁止写文件；commit/push/create MR 仅 Orchestrator 执行
- 改动越界拒绝；最小 diff

### 6.1 汇总报告（主交付物）

`report.json`（及给 Dify 的同等结构）至少包含：

```json
{
  "runId": "...",
  "summary": {
    "totalClusters": 0,
    "fixed": 0,
    "unfixed": 0
  },
  "fixed": [
    {
      "clusterId": "...",
      "defectIds": [],
      "mrUrl": "...",
      "rootCauseSummary": "...",
      "verify": { "command": "...", "ok": true }
    }
  ],
  "unfixed": [
    {
      "clusterId": "...",
      "defectIds": [],
      "reasonCode": "not_actionable|verify_failed|no_test_command|push_failed|...",
      "reasonDetail": "完整说明……",
      "artifacts": { "rootCause": "...", "solution": "..." }
    }
  ]
}
```

## 7. Stack Profile

### 7.1 一期内置

- `node-web`：Vue / Vite / Webpack 等前端 Web
- `node-lib`：纯 Node/TS 库
- `electron`：检测 `electron` 依赖；默认偏单元/可无头测试，完整 E2E 需 prompt 显式开启

### 7.2 识别与覆盖优先级

1. Run 级 `userPrompt` / `verifyOverrides`
2. `workDir` 或仓内 `.bugfix.yml`
3. Profile 自动探测（lockfile、`package.json` scripts、vitest/jest 等）
4. 仍不确定 → 报告待指引，不开 MR

### 7.3 扩展

新增 Profile 文件并注册即可（如未来 `java-maven`），Orchestrator 不改。

## 8. 内置 Skills（模型选择性调用）

> 对标：Claude Agent Skills（元数据预载 + 按需读全文）、NanoHarness Lazy Skills、Hermes/agentskills.io、调研报告「任务专用 procedural knowledge」。  
> 原则：**内置优秀实践，目录常驻；全文不预灌；模型用 `Skill` 工具按需加载。**

### 8.1 加载与隔离

| 项 | 约定 |
|----|------|
| 发行位置 | Agent 包内 `skills/`（或 `.claude/skills/`），随安装分发 |
| 会话可见 | Implement / Iterate（及可选只读分析阶段）通过 SDK `plugins` 或注入工作区 `.claude/skills` 暴露 |
| 发现方式 | 启动只加载各 skill 的 `name` + `description`（YAML frontmatter） |
| 调用方式 | 模型自主 `Skill` tool → 再读完整 `SKILL.md` / 引用文件 / 可执行脚本 |
| SDK 配置 | `skills: "all"` 或显式白名单；`allowedTools` 含 `Skill`；避免依赖用户全局 `~/.claude`（多租户/可复现跑用包内 skills） |
| 用户扩展 | `{workDir}/.bugfix/skills/` 或仓内 `.claude/skills/` 叠加；同名默认 **用户覆盖内置** |
| 禁用 | `options.skills.disabled[]` 或 `options.skills.enabled[]`（enabled 非空则仅启用列表） |
| Dify 指导 | `userPrompt` 可提示「优先用某某 skill」；不强制加载，仍由模型选择（可记审计：实际调用了哪些 skill） |

### 8.2 一期内置目录（建议包）

每个 skill：`skills/<id>/SKILL.md`（+ 可选 `references/`、`scripts/`）。`description` 必须写清 **做什么 + 何时用**，便于模型匹配。

| Skill ID | 用途 | 主要来源/对标 |
|----------|------|----------------|
| `systematic-debugging` | 系统化排障：复现→定位→最小修复→验证 | Superpowers / 业界调试流程 |
| `root-cause-tracing` | 从堆栈/症状向上追根因，避免治标 | 调试类 skills |
| `hierarchical-localization` | 文件→符号→编辑点分层定位 | Agentless |
| `minimal-diff` | 最小改动、禁止顺手重构 | NanoHarness Minimal Implementation |
| `test-triage` | 解析失败日志、exit code、筛回归 vs 相关失败 | NanoHarness Test Triage |
| `reproduction-test` | 能写则写最小复现/回归测试 | Agentless reproduction |
| `patch-review` | 对照 Plan 验收标准审 diff | SpecRover Reviewer / Submission Review |
| `vue-debug` | Vue 响应式、生命周期、模板/组合式 API 常见坑 | 前端垂直（可参考旧仓 vue skills） |
| `typescript-null-safety` | TS/JS 空值、类型收窄、异步错误 | 一期栈 |
| `electron-process-boundary` | 主/渲染进程、preload、IPC、上下文隔离 | Electron Profile |
| `monorepo-workspace` | pnpm/yarn workspace 定位包与测试入口 | 真实仓常见 |
| `verify-green-gate` | 提醒：无 GREEN 不开 MR；探测命令优先级 | 本产品硬门禁 |
| `gitlab-mr-hygiene` | MR 描述应含缺陷 ID、根因、验证结果（文案规范；**不**自行 push） | 交付质量 |

一期可先落地 **核心 6～8 个**（debugging / localization / minimal-diff / test-triage / vue-debug / typescript-null-safety / verify-green-gate / patch-review），其余按栈检测 **条件启用**（如仅 Electron 仓暴露 `electron-process-boundary`）。

### 8.3 与编排阶段的关系

| 阶段 | Skills 策略 |
|------|-------------|
| Localization / RootCause / Plan | 可启用只读向 skills（debugging、localization、vue-debug…）；**无写权限** |
| Implement / Iterate | 全量（或 Profile 过滤后的）可调用 skills + Edit |
| Verify / Deliver | Orchestrator 确定性执行；skills 不替代门禁 |

Skills **增强**模型行为，**不替代** Orchestrator 门禁（GREEN、Scope、确定性 MR）。

### 8.4 质量与演进

- 每个内置 skill 需有简短「适用/不适用」说明，避免误触发
- Run 报告记录 `skillsInvoked[]`（名称与阶段），便于评测 skill 贡献
- 后续可从开源 skill hub / 旧仓 `prompt/skills` **精选移植**，不整库无差别灌入
- 禁止把密钥、内网专用流程写进默认内置 skill

## 9. MCP 配置与调用

> 对标：Claude Agent SDK `mcpServers` / `.mcp.json`；旧仓 GitLab MCP、监控 MCP 接入经验。  
> 原则：**可配置、可按 Run 覆盖、工具白名单、密钥不进缺陷正文；模型在允许范围内调用 MCP。**

### 9.1 能力

| 能力 | 说明 |
|------|------|
| 多 Server | 同时挂载多个 MCP（按 `name` 区分） |
| 传输类型 | `stdio`（本地进程）、`http` / `sse` / Streamable HTTP（远程或本机服务） |
| 配置来源优先级 | Run `options.mcp` → `{workDir}/.bugfix/mcp.json` → Agent 本机全局配置 →（可选）仓内 `.mcp.json` |
| 调用方 | 分析/实现阶段由 **模型经 SDK** 调用；Orchestrator 也可对白名单工具做确定性调用（如读缺陷补充信息） |
| 与 Skills | 正交：Skills 是流程知识；MCP 是外部工具/数据源 |

典型用途（示例，非强制内置）：文档检索、内部缺陷详情 API、GitLab/监控只读工具、浏览器/复现辅助等。  
**Git push / 建 MR 仍走 Orchestrator**，即使某 MCP 提供写仓工具，默认也 **deny** 写类 MCP（可配置放开）。

### 9.2 配置形状（与 SDK 对齐的简化层）

```json
{
  "mcp": {
    "enabled": true,
    "servers": {
      "docs": {
        "type": "http",
        "url": "https://example.com/mcp",
        "headers": { "Authorization": "Bearer ${DOCS_MCP_TOKEN}" }
      },
      "filesystem-extra": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/refs"]
      }
    },
    "allowedTools": ["mcp__docs__*", "mcp__filesystem-extra__read_*"],
    "deniedTools": ["mcp__*__delete_*", "mcp__*__push_*"]
  }
}
```

- 环境变量占位 `${VAR}` 由 Agent 在本机展开；**禁止**把真实 Token 写进 Excel / Dify 对话明文持久化字段（Dify 侧用密钥变量）
- `allowedTools` 映射到 SDK `allowedTools` 中的 `mcp__<server>__<tool>` 或通配
- 未配置 `mcp` 或 `enabled=false`：行为与无 MCP 一致，仅内置工具 + Skills

### 9.3 阶段与权限

| 阶段 | MCP 策略 |
|------|----------|
| Localization / RootCause / Plan | 默认仅 **只读** MCP（读文件/查缺陷/查文档）；写操作 deny |
| Implement / Iterate | 按 `allowedTools`；仍建议限制破坏性工具 |
| Verify / Deliver | MCP 不替代测试门禁与 GitLab 确定性交付 |

### 9.4 安全与可观测

- 默认不加载用户全局 Claude MCP（可复现）；只加载显式配置
- stdio 命令需路径/命令白名单或用户明确确认（防任意进程拉起）
- 报告记录 `mcpServersAttached[]`、`mcpToolsInvoked[]`（脱敏）
- 连接失败：`best_effort` 跳过该 server 并警告；`required` 则该簇记未修复并说明（不阻断整次日批除非配置 required 且策略要求）

## 10. Dify API 契约（草案）

### `POST /v1/runs`

```json
{
  "workDir": "D:/work/my-app-fix",
  "defects": [],
  "userPrompt": "可选：monorepo 请在 apps/desktop 下 pnpm test",
  "options": {
    "maxIterate": 3,
    "stackProfile": "auto",
    "gitlabHost": "https://gitlab.example.com",
    "skills": {
      "enabled": [],
      "disabled": [],
      "extraDirs": []
    },
    "mcp": {
      "enabled": true,
      "servers": {},
      "allowedTools": [],
      "deniedTools": []
    }
  }
}
```

响应：`202 { "runId": "..." }`

### `GET /v1/runs/:runId`

返回阶段、簇进度、最终 report（含各簇 `mrUrl` / 跳过原因 / 验证摘要）。  
若启用远程存储：可同时返回 `remoteRef`（对方系统中的记录 id/url）；读取时可 `options.preferRemote=true` 与本地合并（冲突策略：默认以本地 run 目录为准，远程作备份/看板）。

### 远程存储适配（可选，`options.storage`）

```json
{
  "storage": {
    "enabled": true,
    "baseUrl": "https://remote.example.com/api",
    "mode": "best_effort",
    "sync": ["progress", "report", "cluster_results"]
  }
}
```

- `mode=best_effort`：远程失败只记警告，本地与 MR 照常
- `mode=required`：关键检查点（如 run 结束写报告）失败则 run 标记 `storage_failed`（MR 是否已创建按实际为准，需在报告中标明）

## 11. GitLab 交付

- 分支：`bugfix/{runId}/{clusterId}`
- Orchestrator 确定性：`commit` → `push` → Create Merge Request API
- MR 正文：簇内缺陷 ID、根因、验证命令与结果、prompt 摘要
- **永不自动 merge**
- Token：本机环境变量（如 `GITLAB_TOKEN`）
- 仅出现在报告 **`fixed[]`**；未修复簇不得半开 MR

## 12. 与旧项目关系

可参考复用（思想/代码级）：

- `aiservice-for-monitor` 的 `agent-fix` runner、分层 Autofix 语义、handoff、GitLab MR publish

不应整仓搬运：

- Redis 任务主存、多租户缓存、服务端 ephemeral 且不装依赖的模型
- Seer 式「根因后等人点继续」的产品交互

## 13. SOTA 调研采纳清单（已纳入规格）

### P0（一期必做）

1. 层次化 Localization artifact（Agentless）
2. Verify 由 Orchestrator 执行并记录 exit code / 失败摘要（SWE 真值）
3. Implement 后 Static check 反馈环（SWE-agent ACI）
4. Architect–Editor 分离：分析只读 / 实现可写（Aider / Seer）
5. 确定性 GitLab 交付（Samba）
6. Fixability：可修→冲 MR；不可修→完整未修复说明（**非** Seer 中间停等）
7. **内置 Skills 包 + 模型按需 `Skill` 调用**
8. **可配置 MCP 挂载 + 工具白名单调用**
9. **全自动双结局 + 汇总报告**（`fixed[]` / `unfixed[]`）——日批主交付

### P1（强烈建议，可紧随一期）

1. 轻量 Repo Map（Aider）
2. 难簇多样本 + Verify 选优（Agentless / OpenHands）
3. 独立 Reviewer 步（自动 Iterate，不等人）
4. 复现步骤或最小复现测试写入 MR（Agentless）
5. Iterate 只回灌结构化失败片段（Seer pr_iteration）
6. 按 Stack Profile **条件暴露**垂直 skills；报告 `skillsInvoked[]`
7. MCP `required`/`best_effort`、stdio 命令白名单、报告 `mcpToolsInvoked[]`

### 明确不纳入一期

- Hermes 全量个人助手 / 跨会话记忆平台
- 无验证的 webhook→PR 捷径
- 纯 bash-only 作为默认改码界面
- 激进对话压缩替代落盘轨迹
- 把全部开源 skill 无筛选塞进上下文（只内置精选 + 懒加载）
- 默认放开 MCP 写仓/破坏性工具（须显式 allow）
- **产品级 stopping_point 等人继续**（与 G13 冲突）

完整论证见调研报告与 Seer 深潜。

## 14. 修订记录

| 日期       | 说明                                             |
| ---------- | ------------------------------------------------ |
| 2026-10-14 | 初版固化（对话确认骨架）                         |
| 2026-10-14 | 按 SOTA 调研反哺流水线与采纳清单（P0/P1）        |
| 2026-10-14 | 澄清：自身不做存储，但可调用外部接口读写远程数据 |
| 2026-10-14 | 内置 Skills：业界精选 + 模型选择性调用           |
| 2026-10-14 | 支持可配置 MCP 挂载与调用                        |
| 2026-10-14 | 增加 Seer Autofix 深潜报告交叉引用               |
| 2026-10-14 | 全自动双结局：可修→MR，不可修→完整报告；无中间等人 |
| 2026-10-14 | 明确以 npm 包（CLI + 库 API）形态分发 |
