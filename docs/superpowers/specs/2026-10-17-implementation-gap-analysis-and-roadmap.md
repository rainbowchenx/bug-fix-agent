# BugFix Agent 现状分析：实现 / 架构 / 预期效果 / 缺口 / 后续安排

> 基线：`main` @ `5255a6a`（2026-10-17），`npm test` 26 文件 78 用例全绿，`tsc --noEmit` 无错。  
> 方法：逐文件通读 `src/`、`skills/`、`test/`，对照 [设计规格](2026-10-14-local-bugfix-agent-design.md)、[MVP 计划](../plans/2026-10-14-local-bugfix-agent-mvp.md)、[P1 门禁计划](../plans/2026-10-15-p1-quality-gates.md)、[LangGraph 引擎说明](../../langgraph.md) 以及三份调研报告中的 P0/P1 采纳清单，并核对 `@anthropic-ai/claude-agent-sdk` 的类型声明。  
> 定位：本文是对「当前文档设计能否达成项目最终目的」的理论评估与后续任务固化，**不是**新的功能规格。后续规格/计划应引用本文的编号（如 `GAP-A1`）。

---

## 0. 结论先行

**项目最终目的**（规格 G13/G14）：Dify 每日把缺陷整表 + `workDir` 一次交给本地 Agent，Agent 全自动跑完，产出「已修（含 `mrUrl`）/ 未修（含完整原因）」的双结局报告，无中间等人。

**结论：骨架方向正确、文档设计在"编排与交付"层面足以支撑最终目的；但在"修复正确性的真值来源"与"真实仓库可运行性"两个层面，当前设计与实现都不足以在第一次真实日批中产出可信结果。** 具体：

| 维度 | 评价 |
|------|------|
| 产品形态（npm 包 + 127.0.0.1 HTTP + 文件态 run 目录 + 双结局报告） | ✅ 已落地，与规格一致 |
| 编排骨架（normalize → aggregate → analyze → prepare → implement → static → verify → classify → review → deliver） | ✅ 已落地，且有 pipeline / LangGraph 两套等价实现与 parity 测试 |
| 门禁语义（无 GREEN 不开 MR、fixability 三态、Smart Routing、Reviewer、Known Issues） | ✅ 控制流已落地；⚠️ 但多数门禁的**输入**是弱的或缺失的（见 §4） |
| 修复正确性真值 | ❌ 当前 GREEN = "既有测试没挂"，是**回归门禁**而非**修复门禁**；对来自生产的缺陷几乎无区分度（§4.1） |
| 真实仓库可运行性 | ❌ analyze 产物解析在真实输出下必然失败（已复现）、工作区无清理/隔离、无超时、包管理器硬编码 `npm install`、Skills 极可能未真正加载、Scope lock 实跑失效、Reviewer 看不到 diff（§5 阻断级） |
| 规格声明但未实现 | ⚠️ `.bugfix.yml`、`options.skills` 生效、MCP allow/deny、StorageAdapter 接线、`concurrency`、CLI `run`、报告 `skillsInvoked/mcpToolsInvoked`、Localization artifact 等（§6） |
| 效果可测性 | ❌ 全部测试为 mock；没有一次真实端到端运行记录；没有评测集，预期效果只能理论推断（§4.4） |

**一句话**：文档把"怎么编排、怎么收尾、怎么写报告"说清楚了，但没有把"怎么证明这个 MR 真的修了这个 bug"说清楚；实现则在"能在真实 Git 仓库上稳定跑"这件事上还差一轮工程加固。两者补齐后，设计可以达成最终目的。

---

## 1. 最终目的拆解（评估标尺）

把 G1–G14 压缩为五条价值链，后文均按此评估：

| # | 价值链 | 成立条件 |
|---|--------|----------|
| V1 | **全自动** | 任一簇在任何失败点都能自动收尾为 `unfixed`，整批不会卡死、不会等人 |
| V2 | **可信的"已修"** | `fixed[]` 里的 MR，人审一次合并率要显著高于随机改码；否则日报变成噪声 |
| V3 | **有用的"未修"** | `unfixed[]` 的 `reasonCode/Detail` 能让人直接判断下一步（环境问题 / 需补信息 / 模型不会修） |
| V4 | **真实仓库可运行** | 在一期目标栈（Vue / Node / TS / Electron，npm/pnpm/yarn，monorepo 常见）上 clone→install→test 能稳定跑通 |
| V5 | **可运维** | 进程崩溃可恢复、可取消、可观测、可配置、密钥不泄露 |

---

## 2. 当前实现盘点

### 2.1 模块清单与状态

| 模块 | 文件 | 状态 | 备注 |
|------|------|------|------|
| CLI | `src/cli.ts` | 🟡 | `serve` / `version` 可用；`run` 仅占位报错 |
| HTTP | `src/http/app.ts`, `src/index.ts` | 🟢 | `POST/GET /v1/runs`、`/health`；绑定 127.0.0.1；GET 需 `workDir` 查询参数 |
| Schema | `src/types.ts`, `src/agent/artifacts.ts` | 🟢 | zod；ReasonCode 17 个；RootCause/Solution 对齐 Seer |
| Run 存储 | `src/runs/store.ts`, `src/workspace/paths.ts` | 🟢 | `{workDir}/.bugfix-runs/{runId}/` 文件态 |
| Normalize / Aggregate | `src/pipeline/normalize.ts`, `aggregate.ts` | 🟡 | 规则版：`repoUrl + fingerprint`；指纹 = 标题+pageUrl+栈前 200 字符的 hash，实际近似"一行一簇" |
| Profile / Verify 解析 | `src/profiles/*`, `src/pipeline/verify.ts` | 🟡 | 三个 Profile 仅影响打分；install 恒为 `npm install`；test 仅看 `scripts.test/test:unit/vitest`；userPrompt 仅识别 ``verify:`cmd` `` |
| Workspace | `src/workspace/git.ts` | 🔴 | clone/fetch 可用；**不清理、不复位基线分支**（§5 A1） |
| SDK 封装 | `src/agent/sdk-runner.ts` | 🟡 | analyze/implement/review 三模式工具白名单正确；Skills 挂载方式与 SDK 约定不符（§5 A5） |
| Analyze | `src/pipeline/analyze.ts`, `fixability.ts`, `failure-modes.ts` | 🟢 | IRON LAW / 失败模式 / 三态门禁 / `target_files` 已进 prompt |
| Implement + Scope lock | `src/pipeline/implement.ts`, `scope-lock.ts` | 🔴 | 真实路径 `changedFiles: []` → scope lock 软通过，仅靠 prompt 约束（§5 A4） |
| Static check | `src/pipeline/static-check.ts` | 🟡 | 探测 typecheck/lint；**无基线对比**，仓库原有错误会误杀所有簇 |
| Verify | `src/pipeline/verify.ts`, `prepare.ts` | 🟡 | Orchestrator 真实执行；**无超时、无基线、无 CI 环境变量** |
| Smart Routing | `src/pipeline/verify-classify.ts`, `log-snip.ts` | 🟢 | 启发式分类 + 日志裁剪，有单测 |
| Reviewer | `src/pipeline/review.ts` | 🔴 | 只读模式正确，但 **prompt 不含 diff、工具无 Bash**，无法看到改了什么（§5 A6） |
| Deliver | `src/pipeline/deliver.ts`, `src/gitlab/client.ts` | 🔴 | `checkout -B` + `add -A` + 吞掉 "nothing to commit" → 可能推送空分支并开空 MR；无 `has_code_changes` 检查；MR 正文无缺陷 ID；仅支持 https URL |
| Known Issues | `src/pipeline/known-issues.ts` | 🟢 | 预算耗尽文案规范 |
| Skills | `skills/*/SKILL.md`, `src/skills/manifest.ts` | 🟡 | 8 个 SKILL.md 均为 10–27 行提纲；`filterSkills` 未被 runner 使用 |
| MCP | `src/mcp/load-config.ts` | 🟡 | 合并 + `${ENV}` 展开可用；`allowedTools/deniedTools`、stdio 白名单、analyze 阶段 deny 写工具均未接到 SDK |
| Storage | `src/storage/*` | 🟡 | 接口 + noop + http stub；**runner 从未调用** |
| LangGraph 引擎 | `src/graph/*`, `langgraph.json` | 🟢 | 与 pipeline 等价；checkpointer 可挂但 HTTP 路径未用 |
| 测试 | `test/**` | 🟡 | 78 用例全部 mock handler；无真实 git/SDK e2e |

🟢 可用且与规格一致 🟡 部分实现/与规格有偏差 🔴 存在会导致真实运行失败或产出错误结果的问题

### 2.2 对规格 G1–G14 的核对

| 目标 | 现状 |
|------|------|
| G1 npm 包 + CLI + 库 API | ✅（CLI `run` 缺） |
| G2 Dify 负责校验/传表/选 workDir | ✅ 契约已定；❌ 未提供 Dify Custom Tool OpenAPI 样例 |
| G3 一次整表 + 内部归一/聚合 | ✅ 归一；⚠️ 聚合退化为近似一行一簇，无簇大小上限/拆分 |
| G4 一簇一 MR | ✅ 控制流；❌ 同仓多簇时分支/工作区串扰会让 MR 互相包含（§5 A1） |
| G5 本地 clone/执行；自身不存储；可调外部接口 | ✅ 本地；❌ StorageAdapter 未接线 |
| G6 无 GREEN 不开 MR | ✅ 控制流；⚠️ GREEN 语义弱（§4.1） |
| G7 验证命令自动探测 + userPrompt 覆盖 | 🟡 探测浅；`.bugfix.yml` 未实现 |
| G8 Claude Agent SDK 改码 + 外层编排 | ✅ |
| G9 push + 建 MR、不 merge | ✅ |
| G10 Vue/Node/TS/Electron Profile 可切换/识别/扩展 | 🟡 识别可用；install/test 命令基本不随 Profile 变化；无 pnpm/yarn/monorepo |
| G11 内置 Skills，模型按需调用，可扩展/禁用 | ❌ 极可能未真正加载；enabled/disabled 未生效；用户扩展目录未实现 |
| G12 可配置 MCP，白名单调用 | 🟡 服务器可挂；白名单/黑名单未生效 |
| G13 全自动无断点 | ✅ 无 AskUser；❌ 但无超时 → 可能"无限等待子进程"，等价于卡死 |
| G14 日报式交付 | ✅ 报告结构；⚠️ 缺可追溯字段（headSha、profile、迭代数、exit code、skills/mcp 调用） |

---

## 3. 架构评估

### 3.1 做对的事

1. **确定性 Orchestrator + 模型只在 analyze/implement/review 三个受限会话里出现**。install/test/git/MR 全部由代码执行，不依赖模型"自称通过"，这是相对多数开源 bugfix agent 的最大优势，也符合三份调研的一致结论。
2. **Architect–Editor 分离**：analyze/review 只读工具集，implement 才开 `Edit`。
3. **双结局收尾完整**：每个失败点都映射到 `ReasonCode`，`unfixed` 不会静默丢。
4. **文件态状态 + 无业务库**：契合"本机 Dify 串联"的部署形态；`GET` 任何时候可读。
5. **两套引擎共享同一组 `src/pipeline/*` 步骤函数**，并有 parity 测试，LangGraph 版为将来 checkpoint/resume、Studio 可视化留了口子。

### 3.2 架构层面的担忧

| 项 | 说明 | 建议 |
|----|------|------|
| **双引擎长期并存** | `runner.ts` 与 `cluster-graph.ts` 各 ~400 行重复控制流，任何门禁改动要改两处 + 维护 parity 测试 | 在 Phase C 收敛为单引擎（倾向 LangGraph：状态显式、可 checkpoint；或保留 pipeline 删 graph，取决于是否真要 Studio） |
| **工作区模型**：`{workDir}/repos/<repo>` 一仓一目录、跨簇跨 run 复用 | 节省 clone，但与"一簇一 MR、互不影响"冲突；当前无任何清理 | 一簇一 `git worktree`（共享对象库，独立工作树），或每簇前 `reset --hard && clean -fdx && checkout <base>` |
| **门禁的输入质量** | 控制流完备，但 scope lock 没有真实 changedFiles、reviewer 没有 diff、static/verify 没有基线 | 把 "orchestrator 采集真值 → 喂给门禁" 作为统一原则补齐（Phase A/B） |
| **Skills 挂载依赖 SDK 插件约定** | 现在把 `skills/` 直接当 plugin 根目录传入 | 按 SDK 约定补 `.claude-plugin/plugin.json`，或把 skills 复制到仓库 `.claude/skills` 并 `settingSources:["project"]`；统一用 SDK `skills` 选项而非 `allowedTools` 里的 `Skill` |
| **类型与规格漂移** | `options.mcp` 形状、`options.skills`、`options.storage`、`stackProfile`、`gitlabHost` 等规格 §9/§10 字段与 `CreateRunOptionsSchema` 不一致 | 以代码为准回写规格，或以规格为准补 schema（§8） |

---

## 4. 预期效果的理论分析

### 4.1 "没有 GREEN 就没有 MR" 的真实强度

当前 GREEN 的定义是：**修改后，仓库既有 `npm test` 全部通过**。

- 对来自生产的缺陷（Excel 里的标题 / 堆栈 / 页面 URL），**既有测试几乎必然不覆盖该缺陷**（否则不会上线）。因此修改前 `npm test` 已是绿的，修改后仍是绿的——GREEN 对"是否修好"**没有区分度**，它只能保证"没把别的弄坏"。
- 换言之，当前 GREEN 是**回归门禁**，不是**修复门禁**。`fixed[]` 中的 MR 其正确性完全取决于模型一次改码的质量，再加一个看不见 diff 的 reviewer。
- 调研报告（SOTA §6 P1-10 "Reproduction 辅助"、Seer 深潜 §8）都指出了这一点，但规格 §6 把它放在 P1 且未进实现计划。

**推论**：要让 V2 成立，必须引入至少一种"修复真值"：
1. **复现测试优先**（首选）：implement 分两段——先写一个能复现缺陷的失败测试（RED），再修（GREEN）。能写出 RED 的簇，其 MR 置信度高；写不出 RED 的簇，报告显式标注 `verifyLevel: regression_only` 并建议 MR 以 Draft 打开。
2. **基线差分**：修复前先跑一次 static/verify 作为基线，只把"新增失败"视为阻断；同时避免仓库原有 lint/tsc 错误误杀所有簇（当前 static check 的直接问题）。
3. **Reviewer 真审 diff**：由 Orchestrator 把 `git diff` 文本喂入 review prompt。

### 4.2 聚合（G3/G4）的实际效果

`deriveFingerprint` = sha1(规范化标题 | pageUrl | 堆栈前 200 字符)。日常 Excel 两行能完全命中同一指纹的概率很低，实际会退化成**一缺陷一簇一 MR**。这不影响正确性，但 G3 的"聚合"价值目前接近 0，且没有"过大簇拆分"保护。

### 4.3 可运行性（V4）对结果分布的影响

在一期目标栈上，第一次真实日批最可能的 `unfixed` 分布（理论推断）：

| reasonCode | 触发原因（当前代码） | 预期占比 |
|------------|---------------------|----------|
| `analyze_failed` | **GAP-A8**：ROOT_CAUSE/SOLUTION 双 JSON 解析必然失败 → 不修复此项时几乎 100% 的簇停在这里 | 极高（阻断） |
| `no_test_command` | 大量 Vue 前端仓没有 `scripts.test` | 高 |
| `prepare_failed` | pnpm/yarn 仓用 `npm install` 失败；私有 registry；monorepo 子包 | 高 |
| `static_check_failed` | 仓库原有 lint/tsc 错误（无基线） | 中 |
| `env_verify_failed` | 测试需要浏览器/服务；启发式误判（如日志里恰有 "timed out"） | 中 |
| run 整体 `failed` | reviewer 输出解析抛错未被捕获（GAP-B3），一簇失败连带后续簇全部丢失 | 中 |
| 模型真正"修不了" | — | 低（被前面的工程原因淹没） |

也就是说，**首轮结果会主要反映 harness 缺陷而不是模型能力**：先是 GAP-A8 让所有簇停在 analyze；修掉后，再由 install/test 兼容性主导。报告看起来像"Agent 不行"，实际是 harness 没就位。这是 Phase A 必须先做的原因。

### 4.4 为什么现在无法给出量化预期

- 78 个测试全部用 `handlers` 注入 mock，`runAgentSession` 的真实分支、`ensureRepo/deliverFix` 的真实 git 分支从未在仓内被执行过。
- 没有评测集（调研 §8 建议 10–20 条历史缺陷 + 已合并 MR 作 oracle）。
- 因此"GREEN 率 / MR 率 / 一次合并率 / 平均 diff 行数 / 费用"全部未知。Phase A 末尾需要建立最小 e2e 与评测集，之后所有"效果"讨论才有数据。

---

## 5. 缺陷与风险清单（按严重度）

### 阻断级（第一次真实运行即会出错或产出错误 MR）

| ID | 问题 | 位置 | 影响 |
|----|------|------|------|
| GAP-A1 | 工作区不清理、不复位：同仓第二簇在第一簇的 `bugfix/*` 分支和脏工作树上继续；`deliver` 用 `add -A` 把残留一起提交；"nothing to commit" 被吞掉后仍 push + 开 MR | `workspace/git.ts` `ensureRepo`、`pipeline/deliver.ts` | MR 互相包含、空 MR、`unfixed` 簇的半成品泄漏进下一簇 |
| GAP-A2 | 所有子进程（install / static / verify）与 SDK 会话都没有超时；未设置 `CI=1` | `prepare.ts`、`static-check.ts`、`verify.ts`、`sdk-runner.ts` | 一个 watch 模式的 `jest`/卡死的 e2e 让整个日批永久挂起，违背 G13 |
| GAP-A3 | 包管理器硬编码 `npm install`；不识别 `pnpm-lock.yaml` / `yarn.lock` / workspace | `profiles/detect.ts` `scriptsFromPackage` | pnpm/yarn 仓必然 `prepare_failed` |
| GAP-A4 | Scope lock 实跑失效：真实 `implementCluster` 返回 `changedFiles: []`，`checkScopeLock` 对空列表直接通过 | `pipeline/implement.ts` L73–80 | 规格 §6 "改动越界拒绝" 实际只是 prompt 建议 |
| GAP-A5 | Skills 极可能未加载：`plugins:[{type:'local', path: skills/}]` 但 `skills/` 下无 `.claude-plugin/plugin.json`（SDK 插件要求），且未用 SDK `skills` 选项；implement/review 会话根本没传 `skillsDir`；`options.skills.enabled/disabled` 无任何消费者 | `agent/sdk-runner.ts`、`pipeline/implement.ts`、`pipeline/review.ts` | G11 实际为 0；需真实运行用 `supportedCommands/skills` 列表验证 |
| GAP-A6 | Reviewer 盲审：prompt 只有 rootCause/solution/verify 日志，没有 diff；工具集无 Bash 无法自取 `git diff` | `pipeline/review.ts` | Reviewer 门禁近似随机 |
| GAP-A7 | 无 `has_code_changes` 门禁；Seer 深潜 §10 列为必抄 | `pipeline/deliver.ts` | 模型没改任何文件也会开 MR |
| GAP-A8 | 分析产物解析必然失败：prompt 要求同一段文本输出 `ROOT_CAUSE {…}` 与 `SOLUTION {…}`，而 `parseLabeled` 的正则 `ROOT_CAUSE[\s\S]*?(\{[\s\S]*\})` 贪婪匹配到**最后一个** `}`，把两个对象连同中间文字一起交给 `JSON.parse`（已用 `node -e` 复现：`Unexpected non-whitespace character after JSON`）；异常被 `analyzeCluster` 捕获为 `analyze_failed`。现有单测只覆盖 prompt 文本与 `mockArtifacts` 路径，未覆盖真实解析 | `pipeline/analyze.ts` `parseLabeled` | 真实运行中几乎每个簇都会在 analyze 阶段 `unfixed`，流水线后半段永远走不到 |

### 高

| ID | 问题 | 位置 |
|----|------|------|
| GAP-B1 | static check / verify 无基线：仓库原有 lint/tsc/测试失败会让所有簇 `static_check_failed`/`verify_failed` | `runner.ts`、`cluster-graph.ts` |
| GAP-B2 | 无复现测试机制；implement 工具集无 `Write`，模型无法新建测试文件 | `sdk-runner.ts` `IMPLEMENT_TOOLS` |
| GAP-B3 | `reviewCluster` 的 `parseReviewResult` 用 `extractJsonObject`（首个 `{` 到最后一个 `}`），reviewer 多说一句含花括号的话即解析失败并抛错（未被 runner 捕获 → 整个 run `failed`） | `pipeline/review.ts`、`runner.ts` |
| GAP-B4 | MCP `allowedTools/deniedTools` 未传 SDK；`defaultDeniedToolsForAnalyze` 从未被调用；stdio 命令无白名单 | `mcp/load-config.ts`、`sdk-runner.ts` |
| GAP-B5 | `git commit` 未配置 identity；无全局 git user 的机器上 deliver 必失败 | `deliver.ts` |
| GAP-B6 | token 以 `oauth2:<token>@` 形式写进 clone URL 并持久化到 `.git/config` | `workspace/git.ts` `withTokenUrl` |
| GAP-B7 | 进程崩溃后 run 永远 `running`；无取消 API（`cancelled` 码无人产出）；LangGraph checkpointer 未接 HTTP | `runs/runner.ts`、`http/app.ts` |

### 中

| ID | 问题 |
|----|------|
| GAP-C1 | 聚合近似一行一簇；无簇上限/拆分；无跨缺陷相似度 |
| GAP-C2 | `.bugfix.yml` 未实现；userPrompt 只认 ``verify:`…` `` |
| GAP-C3 | `options.concurrency` / `defaultConcurrency` 未实现（当前全串行，可接受但要在文档说明） |
| GAP-C4 | 报告缺 `headSha/baseCommit`、`profileId`、`iterations`、exit code、`skillsInvoked[]`、`mcpToolsInvoked[]`、耗时/费用、`verifyLevel` |
| GAP-C5 | MR 正文缺缺陷 ID、复现步骤；无 Draft 选项（规格 §11、Seer P1-13） |
| GAP-C6 | `projectIdFromRepoUrl` 仅支持 https；`git@host:group/repo.git` 直接抛错 |
| GAP-C7 | StorageAdapter 未接线，`options.storage` 不在 schema |
| GAP-C8 | CLI `run` 未实现；无 Dify OpenAPI 样例 |
| GAP-C9 | Localization 没有独立 artifact（规格 P0-1）；无 Repo Map |
| GAP-C10 | 8 个 Skill 均为提纲级，距"业界优秀 Skills"有差距；无 `electron-process-boundary`、`monorepo-workspace`、`reproduction-test`、`gitlab-mr-hygiene` |

### 低

- `GET /v1/runs/:id` 必须带 `workDir`，Dify 侧需要自行记住；可考虑服务端维护 runId→workDir 索引。
- `verify.logTail` 截 4000 字符、`snipVerifyLog` 2500 字符，长堆栈可能丢关键帧。
- `langgraph.json` 指向 `src/graph/langgraph.ts`，发布包内运行需改指向 `dist`。

---

## 6. 未完成任务核对（对规格 / 计划 / 调研清单）

### 6.1 规格 §13 P0（"一期必做"）

| # | 项 | 状态 |
|---|----|------|
| 1 | 层次化 Localization artifact | ❌ 只在 prompt 里要求"Localize"，无落盘 artifact |
| 2 | Verify 由 Orchestrator 执行并记录 exit code / 失败摘要 | 🟡 执行 ✅；exit code 未记录 |
| 3 | Implement 后 Static check 反馈环 | 🟡 有；无基线、无"新引入才阻断" |
| 4 | Architect–Editor 分离 | ✅ |
| 5 | 确定性 GitLab 交付 | 🟡 有；见 GAP-A1/A7/B5 |
| 6 | Fixability 双结局 | ✅ |
| 7 | 内置 Skills + 按需调用 | ❌ 见 GAP-A5 |
| 8 | 可配置 MCP + 白名单 | 🟡 可挂载；白名单 ❌ |
| 9 | 全自动双结局 + 汇总报告 | ✅ |

### 6.2 规格 §13 P1

| # | 项 | 状态 |
|---|----|------|
| 1 | 轻量 Repo Map | ❌ |
| 2 | 难簇多样本 + Verify 选优 | ❌ |
| 3 | 独立 Reviewer | 🟡 有；盲审（GAP-A6） |
| 4 | 复现步骤 / 最小复现测试进 MR | ❌ |
| 5 | Iterate 只回灌结构化失败片段 | ✅ `snipVerifyLog` |
| 6 | 按 Profile 条件暴露垂直 skills；报告 `skillsInvoked[]` | ❌ |
| 7 | MCP `required/best_effort`、stdio 白名单、`mcpToolsInvoked[]` | ❌ |

### 6.3 MVP 计划「验收清单」与「后续 Plan」

- 验收清单中 "`POST` + 轮询得到报告 / 不可修簇无 MR / 可修簇有 `mrUrl`" 均只在 mock 下验证；"**可用 mock/录制或沙箱 GitLab**" 这一条的后半（录制/沙箱）未做。
- 后续 Plan 六项（LLM 聚合、多样本+Reviewer、Electron E2E、Storage 生产实现、GitLab CI → pr_iteration、Dify OpenAPI）中仅 Reviewer 已做。

### 6.4 调研报告建议中尚未吸收的

- SOTA §6 P0-3 "新引入错误才阻断"、P1-7 Repo Map、P1-8 多样本、P1-10 Reproduction。
- Seer 深潜 §10 "开 PR 前检查 has_code_changes"、§12.2 "Repo pin baseCommit"、"Draft MR"、"报告 introspection"；§9 pr_iteration（二期）。
- WorkBuddy §8 P0 三项（IRON LAW、Scope lock、Known Issues）已吸收；但 Scope lock 真实化未完成（GAP-A4）。

---

## 7. 后续完整安排

原则：**先让一个真实仓库可信地跑通（Phase A），再增强真值（Phase B），再做规模与运维（Phase C），最后才是选优/CI 回环等增量（Phase D）**。每阶段给出任务、涉及文件、验收标准；不估算日历时间。

### Phase A — 可信闭环（修阻断级，拿到第一份真实报告）

| 任务 | 内容 | 涉及 | 验收 |
|------|------|------|------|
| A1 工作区隔离 | 每簇独立 `git worktree`（`{workDir}/repos/<repo>/.git` 共享对象库，`{workDir}/worktrees/{runId}/{clusterId}`），或至少每簇前 `reset --hard` + `clean -fdx` + `checkout <base>`；记录 `baseSha`；run 结束按配置清理 | `workspace/git.ts`、`paths.ts`、runner/graph 的 ensure_repo | 同仓两簇各自 MR 只含自己的 commit；`unfixed` 簇不污染下一簇 |
| A2 变更真值与无变更门禁 | implement 后 `git status --porcelain` / `git diff --name-only <baseSha>` 得到 `changedFiles`，驱动 scope lock；deliver 前 `git diff --quiet <baseSha>` 为空 → 新 `reasonCode: no_changes` | `implement.ts`、`deliver.ts`、`types.ts` | 模型零改动不开 MR；越界改动 → `implement_failed` 且 `scope-lock.json` 有真实 violations |
| A3 超时与子进程卫生 | 所有 exec 加 `timeout` + 进程树 kill；SDK 会话加总时长上限；`env: { CI: "1", FORCE_COLOR: "0" }`；超时映射 `env_verify_failed`/`prepare_failed` | `prepare.ts`、`static-check.ts`、`verify.ts`、`sdk-runner.ts`、`config.ts` | 注入 `sleep 999` 的测试命令在限时内收尾为 `unfixed` |
| A4 包管理器与 monorepo 探测 | lockfile → `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile` / `npm ci`；`packageManager` 字段 + corepack；`workspaces`/`pnpm-workspace.yaml` 时根据缺陷文件路径或 userPrompt 选子包 | `profiles/detect.ts`、`profiles/*.ts`、`profiles/types.ts` | fixture：pnpm 仓 / yarn 仓 / npm 仓分别得到正确 install/test 命令 |
| A5 Skills 真正挂载 | 按 SDK 约定：`skills/.claude-plugin/plugin.json` + 将 skill 放到 `skills/skills/<id>/`，或运行时把 skills 复制到 worktree `.claude/skills` 并 `settingSources:["project"]`；使用 SDK `skills: [...]` 替代 `allowedTools` 里的 `Skill`；接通 `options.skills.enabled/disabled`；implement/review 会话也传入 | `agent/sdk-runner.ts`、`skills/`、`implement.ts`、`review.ts`、`runner.ts`、`cluster-graph.ts` | 真实 SDK 会话 `supportedCommands()`/skills 列表包含内置 skills；`disabled` 后不出现 |
| A6 Reviewer 喂 diff | Orchestrator 计算 `git diff <baseSha>`（截断保护）写入 review prompt；考虑给 review 模式加只读 `Bash` 白名单（`git diff/log/show`） | `review.ts`、runner/graph | 单测：prompt 含 diff；真实跑：reviewer reasons 能引用具体 hunk |
| A7 Deliver 加固 | `git -c user.name -c user.email` 或 commit 前配置 identity；MR 正文含缺陷 ID 列表、根因、复现步骤、验证命令与摘要；支持 `options.draftMr`（标题 `Draft:` 前缀）；支持 ssh URL 解析 project path；用 credential helper / `http.extraHeader` 代替 URL 内嵌 token | `deliver.ts`、`gitlab/client.ts`、`workspace/git.ts` | 无全局 git identity 的容器内可 commit；MR 正文符合规格 §11 |
| A8 解析健壮性（**最先做**） | ROOT_CAUSE/SOLUTION 改为平衡括号扫描或要求模型用 ```json 围栏并按标签切段；review 解析同理；解析失败重试一次（短 prompt 只要 JSON）；runner/graph 对 `reviewCluster` 异常做簇级捕获 → `review_failed`，不得拖垮整个 run；补"真实文本样例"解析单测（含两个 JSON、含散文花括号） | `analyze.ts`、`review.ts`、`artifacts.ts`、`runner.ts`、`cluster-graph.ts` | 双 JSON 同段文本正确拆分；reviewer 乱输出只影响本簇 |
| A9 最小 e2e | 用本地 bare 仓作为 "GitLab remote"，`fetchFn` mock MR API，`queryFn` 注入脚本化"模型"：覆盖 clone → implement（真实写文件）→ static → verify（真实 `npm test`）→ deliver（真实 push 到 bare 仓）；另加一个环境变量开关的真实 SDK 冒烟 | `test/e2e/*` | CI 跑 mock 版；本地可跑真 SDK 版 |
| A10 CLI `run` | `bugfix-agent run --work-dir --defects file.json [--engine]`，同步等待并打印报告，退出码反映是否全部 fixed | `cli.ts` | README 示例可直接执行 |

### Phase B — 修复真值与报告质量（让 `fixed[]` 可信）

| 任务 | 内容 | 验收 |
|------|------|------|
| B1 基线差分 | prepare 后、implement 前先跑 static + verify 作为 `baseline.json`；门禁只阻断"新增失败"；基线本身红时在报告标注 `baselineRed: true` | 仓库原有 lint 错误不再误杀；新增失败仍阻断 |
| B2 复现测试优先 | implement 工具集加 `Write`；两段式 prompt：① 在 `target_files` 同包内写最小失败测试并由 Orchestrator 确认 RED；② 修复到 GREEN。写不出 RED → 继续修但报告 `verifyLevel: regression_only`，MR 默认 Draft | `fixed[].verifyLevel ∈ {reproduced, regression_only}`；评测集上 reproduced 组一次合并率显著更高 |
| B3 Localization artifact + Repo Map | analyze 落盘 `localization.json`（suspectFiles → symbols → editTargets）；每仓缓存轻量 outline（文件树 + 导出符号）注入 analyze | `clusters/<id>/localization.json` 存在；scope lock 允许列表可直接取自 editTargets |
| B4 报告扩展 | `fixed/unfixed` 增加 `baseSha`、`branch`、`profileId`、`iterations`、`verify.exitCode`、`durationMs`、`skillsInvoked[]`、`mcpToolsInvoked[]`、`verifyLevel`；run 级 `startedAt/finishedAt/engine` | schema 测试 + README 字段表 |
| B5 MCP 对齐规格 | schema 改为 `{ enabled, servers, allowedTools, deniedTools, mode }`；`allowedTools/disallowedTools` 传 SDK；analyze 阶段自动 deny 写类工具；stdio 命令白名单（配置或确认列表）；`required` 模式连接失败 → 该簇 `unfixed` | 单测 + 真实 MCP（如 filesystem server）冒烟 |
| B6 聚合增强 | 指纹加入"顶层应用栈帧文件:函数"签名；同仓同文件缺陷二次合并；簇大小上限（如 5）超出拆分；可选 LLM 辅助判定"同根因" | 评测集上簇数 < 缺陷数且无错并 |
| B7 Skills 内容提质 | 把 8 个提纲扩成含"适用/不适用/步骤/反例"的完整 SKILL.md；新增 `reproduction-test`、`monorepo-workspace`、`electron-process-boundary`、`gitlab-mr-hygiene`；按 Profile 条件暴露 | 每 skill ≥ 一条真实案例；报告能看到被调用 |

### Phase C — 运维、配置与产品化

| 任务 | 内容 |
|------|------|
| C1 StorageAdapter 接线 | `options.storage{ enabled, baseUrl, mode, sync[] }` 入 schema；runner 在进度更新与报告落盘处调用 `safeSync`；`required` 失败 → run `storage_failed` 标注 |
| C2 并发与生命周期 | 跨仓并行、同仓串行（按 `repoUrl` 分队列）；`POST /v1/runs/:id/cancel`（簇级检查点 + 子进程 kill → `cancelled`）；服务启动时扫描 `running` 的 run 标为 `failed`（或接 LangGraph checkpointer 做 resume） |
| C3 配置文件 | `.bugfix.yml`（仓内 / workDir）：install/test/静态检查命令、子包、skills、mcp；优先级按规格 §7.2 |
| C4 Dify 集成物料 | OpenAPI 3 schema（Custom Tool 直接导入）+ 示例工作流 JSON + 报告渲染模板；`GET` 支持无 `workDir`（服务端索引） |
| C5 引擎收敛 | 评估后保留一套；另一套降级为 adapter 或删除；更新 `docs/langgraph.md` |
| C6 安全 | token 不落 `.git/config`；日志统一脱敏；MCP stdio 白名单默认开启；`.env` 权限提示 |
| C7 文档回写 | 以实现为准修订规格 §9.2/§10 字段；MVP 计划验收清单勾选真实状态；README 增加"已知限制"节 |

### Phase D — 增量（可选，视评测数据决定）

- 难簇多样本（N=2–3 worktree 并行 implement，以 verify/reviewer 选优）。
- GitLab MR note / pipeline webhook → 再入队 iterate（对标 Seer pr_iteration）。
- Electron E2E 可选门闩；Java/Go Profile 扩展点示例。
- Automation tuning（严格/中等/宽松 fixability 阈值）。

### 评测（贯穿 A 末尾起）

- 评测集：10–20 条历史真实缺陷（已合并 MR 作 oracle），覆盖 npm/pnpm、有测/无测、Vue/Node/Electron。
- 指标：`prepare` 成功率、GREEN 率、MR 率、`reproduced` 比例、人审一次合并率、平均 diff 行数、每簇耗时与费用、`unfixed` 原因分布。
- 对照：Phase A 完成（基线）→ B1 → B2 → B6 逐项 A/B；只有数据支持才进入 Phase D。

---

## 8. 对现有文档本身的修订建议

| 文档 | 问题 | 建议 |
|------|------|------|
| 设计规格 §6 | 把"GREEN"当作充分条件；复现测试放 P1 | 增补 §6.2 "修复真值分级"（reproduced / regression_only），复现测试升为 P0 |
| 设计规格 §4 | 目录约定未定义工作区隔离与清理策略 | 增加 worktree 布局与 `baseSha` 记录 |
| 设计规格 §9.2 / §10 | `mcp`、`skills.extraDirs`、`stackProfile`、`gitlabHost`、`storage`、`preferRemote` 与 `CreateRunOptionsSchema` 不符 | 二选一对齐（建议 Phase B5/C1 以规格为准补 schema） |
| 设计规格 §8.1 | Skills 挂载描述为 "plugins 或 .claude/skills"，未说明 SDK 插件清单要求 | 写明选用方案与目录约定 |
| MVP 计划 | 所有 `- [ ]` 未勾选，与"已实现"状态不符；验收清单的"沙箱 GitLab"未完成 | 回填状态；把未完成项迁移到本文 Phase A |
| P1 门禁计划 | 标注 Implemented，但 Reviewer 盲审、Scope lock 软通过 | 增加"已知限制"并引用 GAP-A4/A6 |
| README | 未说明：串行执行、仅 npm、需 `scripts.test`、GET 需 `workDir`、skills 加载状态 | 增加"当前限制"节 |
| `docs/langgraph.md` | 未说明 checkpointer 未接 HTTP、`langgraph.json` 指向 `src` | 补充 |

---

## 9. 核对矩阵（速查）

| 规格承诺 | 代码位置 | 实际 | GAP |
|----------|----------|------|-----|
| 分析产物解析容错 → 该簇失败 | `analyze.ts` | 双 JSON 文本必然解析失败 | A8 |
| 一簇一 MR 互不影响 | `git.ts`/`deliver.ts` | 同仓簇串扰 | A1 |
| 改动越界拒绝 | `implement.ts` | 真实路径空列表 | A4 |
| 无 diff 不开 MR | `deliver.ts` | 无检查 | A7(→A2) |
| Skills 模型按需调用 | `sdk-runner.ts` | 插件路径不符约定 | A5 |
| Reviewer 只读审 diff | `review.ts` | 无 diff 输入 | A6 |
| Static check 只阻断新错 | `static-check.ts` | 无基线 | B1 |
| 复现/最小测试进 MR | — | 无 | B2 |
| Localization artifact | — | 无 | B3 |
| 报告 skills/mcp 调用 | `types.ts` | 无字段 | B4 |
| MCP 白名单 | `load-config.ts` | 未传 SDK | B5 |
| `.bugfix.yml` | — | 无 | C3 |
| StorageAdapter 同步 | `runner.ts` | 未调用 | C1 |
| 并发 | `config.ts` | 未用 | C2 |
| CLI run | `cli.ts` | 占位 | A10 |
| 无中间等待 | 全局 | 无超时 ≈ 可能无限等待 | A3 |

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-17 | 初版：基于 `main@5255a6a` 的实现/架构/效果/缺口分析与 A–D 阶段安排 |
