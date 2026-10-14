# 本地 BugFix Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可本地运行的 BugFix Agent MVP：Dify/`curl` 一次提交缺陷整表 + `workDir`，全自动跑完，产出汇总报告（`fixed[]` 含 `mrUrl` / `unfixed[]` 含完整原因），无中间等人断点。

**Architecture:** 以 **可发布的 npm 包**交付：`bin` CLI（`serve` / `run`）+ 可编程 API；本地 HTTP（127.0.0.1）接收 `POST /v1/runs` 后异步编排；状态落在 `{workDir}/.bugfix-runs/{runId}/`；Orchestrator 确定性执行 clone/install/test/git/MR；Claude Agent SDK 仅用于分析（只读）与实现（可写）；Skills/MCP 随包或可配置挂载。一期不做产品级 stopping_point。

**Tech Stack:** Node ≥20、TypeScript（ESM）、Hono、`@anthropic-ai/claude-agent-sdk`、`zod`、child_process git、Vitest、`tsx`；发布用 `tsup`/`unbuild` 打 `dist/` + `files` 含 `skills/`

**Spec:** [`docs/superpowers/specs/2026-10-14-local-bugfix-agent-design.md`](../specs/2026-10-14-local-bugfix-agent-design.md)  
**Seer 对齐:** [`docs/research/2026-10-14-sentry-seer-autofix-deep-dive.md`](../../research/2026-10-14-sentry-seer-autofix-deep-dive.md)

## Global Constraints

- 自身不做业务 DB；默认文件态；可选 StorageAdapter（MVP 可 stub）
- **可修 → 冲到 MR**；**不可修/失败 → 完整 unfixed 说明**；禁止根因后等人
- **没有 GREEN，就没有 MR**
- 分析阶段禁止 Edit；commit/push/create MR 仅 Orchestrator
- Token：`GITLAB_TOKEN` / `ANTHROPIC_API_KEY` 等走环境变量；不进 Excel
- Windows 路径用 `path.join`；`AGENT`/`BUGFIX` 工作目录用绝对路径
- 测试：`npm test`（Vitest）；每个 Task 有失败先写再实现
- 一期栈 Profile：`node-web` / `node-lib` / `electron`（detect + install/test）
- MVP **可以**先用规则+SDK 最小闭环；P1（多样本、Reviewer、远程存储实现）单列后续 plan

---

## File map（将创建）

| 路径 | 职责 |
|------|------|
| `package.json` / `tsconfig.json` / `vitest.config.ts` | 工程脚手架；`bin.bugfix-agent`、`exports`、`files` |
| `.env.example` | 环境变量说明 |
| `src/cli.ts` | CLI：`serve` / `run` / `version` |
| `src/index.ts` | 库入口 re-export：`createApp`、`startRun`、`loadConfig` |
| `src/config.ts` | 端口、默认并发、模型、路径 |
| `src/types.ts` | Defect / Cluster / Run / Report / ReasonCode（zod） |
| `src/http/app.ts` | Hono app：`POST/GET /v1/runs`、`GET /health` |
| `src/runs/store.ts` | run 目录读写：input/plan/cluster artifacts/report |
| `src/runs/create-run.ts` | 创建 runId、落盘、入队 |
| `src/runs/runner.ts` | 异步跑完整 Run（串行簇，可后续并发） |
| `src/pipeline/normalize.ts` | 缺陷字段归一 |
| `src/pipeline/aggregate.ts` | 规则聚合 → clusters |
| `src/pipeline/fixability.ts` | 轨 A 粗分 + 轨 B 三态消费 |
| `src/pipeline/analyze.ts` | Localization / RootCause / Plan（SDK 只读） |
| `src/pipeline/implement.ts` | SDK 可写改码 + iterate |
| `src/pipeline/verify.ts` | Orchestrator 跑探测到的命令 |
| `src/pipeline/deliver.ts` | git branch/commit/push + GitLab create MR |
| `src/pipeline/report.ts` | 组装 `fixed[]` / `unfixed[]` |
| `src/workspace/git.ts` | clone/fetch/checkout |
| `src/workspace/paths.ts` | repos / run / cluster 路径 |
| `src/profiles/types.ts` | Profile 接口 |
| `src/profiles/detect.ts` | 自动识别 |
| `src/profiles/node-web.ts` 等 | install/test 命令 |
| `src/agent/sdk-runner.ts` | 封装 `query()`：cwd、tools、skills、mcp |
| `src/agent/artifacts.ts` | RootCause/Solution zod schema（对齐 Seer） |
| `src/mcp/load-config.ts` | 合并 options.mcp / `.bugfix/mcp.json` |
| `src/skills/manifest.ts` | 内置 skills 路径暴露给 SDK |
| `skills/*/SKILL.md` | 首批 6～8 个核心 skill |
| `src/storage/adapter.ts` | 接口 + noop / http stub |
| `test/**/*.test.ts` | 单测与集成冒烟 |

---

### Task 1: 工程脚手架（npm 包形态）

**Files:**
- Create: `package.json`, `tsconfig.json`, `vitest.config.ts`, `.env.example`, `.gitignore`, `src/cli.ts`, `src/index.ts`, `src/config.ts`
- Test: `test/unit/config.test.ts`

**Interfaces:**
- Produces: `loadConfig(): AppConfig`；`bin.bugfix-agent`；`exports` → `dist/index.js`；`npm run build` / `npm pack --dry-run`

- [ ] **Step 1: 初始化 package.json（ESM）并安装依赖**

```bash
cd D:\codeOnly\bugfixagent
npm init -y
npm pkg set type=module name=bugfix-agent engines.node=">=20"
npm pkg set bin.bugfix-agent="./dist/cli.js"
npm install hono @hono/node-server zod dotenv @anthropic-ai/claude-agent-sdk
npm install -D typescript tsx vitest @types/node tsup
```

- [ ] **Step 2: 写构建与元数据：`tsconfig` / vitest / tsup（cli+index）/ `.gitignore` / `.env.example`；`files: ["dist","skills","README.md"]`**

`.env.example` 至少含：`PORT=8787`、`ANTHROPIC_API_KEY=`、`ANTHROPIC_BASE_URL=`（可选）、`ANTHROPIC_MODEL=`、`GITLAB_TOKEN=`、`GITLAB_HOST=`

- [ ] **Step 3: 写失败单测 `test/unit/config.test.ts`**（断言默认 PORT=8787）

- [ ] **Step 4: 实现 `src/config.ts` + `src/cli.ts`（`serve`/`--help` 占位）+ `src/index.ts` re-export，使测试通过**

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "chore: scaffold bugfix-agent as npm package with CLI bin"
```

---

### Task 2: 核心类型与报告 schema（zod）

**Files:**
- Create: `src/types.ts`, `src/agent/artifacts.ts`
- Test: `test/unit/types.test.ts`, `test/unit/artifacts.test.ts`

**Interfaces:**
- Produces:
  - `Defect`, `CreateRunRequest`, `Cluster`, `ClusterOutcome` (`fixed`|`unfixed`)
  - `ReasonCode` 枚举：`not_actionable`|`needs_more_context`|`verify_failed`|`no_test_command`|`push_failed`|`localize_failed`|`prepare_failed`|`implement_failed`|`aggregate_skipped`|…
  - `RunReport`：`summary` + `fixed[]` + `unfixed[]`
  - `RootCauseArtifact` / `SolutionArtifact` / `FixabilityAssessment`（对齐 Seer）

- [ ] **Step 1: 写 zod schema 单测（合法 report / 非法 reasonCode 失败）**

- [ ] **Step 2: 实现 schema 与 `parseReport` / `parseRootCause`**

- [ ] **Step 3: 测试通过并 Commit**

```bash
git commit -m "feat: add defect/run/report and Seer-aligned artifact schemas"
```

---

### Task 3: Run 文件存储

**Files:**
- Create: `src/workspace/paths.ts`, `src/runs/store.ts`
- Test: `test/unit/run-store.test.ts`（用 `os.tmpdir()`）

**Interfaces:**
- Produces:
  - `createRunDir(workDir, runId)`
  - `writeJson` / `readJson` for `input.defects.json`, `plan.clusters.json`, `report.json`, `clusters/<id>/*.json`
  - `updateRunMeta(status, progress)`

- [ ] **Step 1: 失败单测：创建 run 目录并写入 input**

- [ ] **Step 2: 实现 paths + store**

- [ ] **Step 3: Commit** `feat: filesystem run store under workDir/.bugfix-runs`

---

### Task 4: HTTP API — 创建 Run + 查询（先同步 stub runner）

**Files:**
- Create: `src/http/app.ts`, `src/runs/create-run.ts`, `src/runs/runner.ts`（先返回空报告 stub）
- Modify: `src/index.ts` 启动 `@hono/node-server`
- Test: `test/integration/runs-api.test.ts`

**Interfaces:**
- `POST /v1/runs` → `202 { runId }`（body: `workDir`, `defects[]`, `userPrompt?`, `options?`）
- `GET /v1/runs/:runId?workDir=` → status + report（完成后）
- `GET /health` → `{ ok: true }`
- MVP：runner 可先 `setImmediate` 写一份空 `report.json`（fixed=0）以打通轮询

- [ ] **Step 1: 集成测试：POST 后 GET 最终 status=completed**

- [ ] **Step 2: 实现 app + create-run + stub runner**

- [ ] **Step 3: Commit** `feat: HTTP POST/GET /v1/runs with async stub runner`

---

### Task 5: Normalize + Aggregate（规则版）

**Files:**
- Create: `src/pipeline/normalize.ts`, `src/pipeline/aggregate.ts`
- Modify: `src/runs/runner.ts` 调用并写 `plan.clusters.json`
- Test: `test/unit/aggregate.test.ts`

**Interfaces:**
- `normalizeDefects(raw): Defect[]`
- `aggregateDefects(defects): Cluster[]`  
  规则 MVP：同 `repoUrl` + 相同规范化 `fingerprint|title` 前缀 → 一簇；过大跨模块后续拆（可先记 TODO）
- 每簇必有 `defectIds[]`, `repoUrl`, `primaryTitle`

- [ ] **Step 1: 单测两条同指纹缺陷合成一簇**

- [ ] **Step 2: 实现 normalize/aggregate，runner 写入 plan**

- [ ] **Step 3: Commit** `feat: normalize and rule-based defect aggregation`

---

### Task 6: Stack Profile 探测 + Verify 命令解析

**Files:**
- Create: `src/profiles/types.ts`, `src/profiles/detect.ts`, `src/profiles/node-web.ts`, `src/profiles/node-lib.ts`, `src/profiles/electron.ts`, `src/pipeline/verify.ts`（先只 resolveCommand）
- Test: `test/unit/profile-detect.test.ts`（用 fixtures 假 package.json）

**Interfaces:**
- `detectProfile(repoPath): ProfileId`
- `resolveVerifyPlan(repoPath, userPrompt?, overrides?): { install[], test[] }`
- 优先级：overrides / userPrompt 解析（简单关键词）→ `.bugfix.yml`（若有）→ package.json scripts

- [ ] **Step 1: fixture 含 vue+vite → node-web；含 electron → electron**

- [ ] **Step 2: 实现 detect + resolveVerifyPlan**

- [ ] **Step 3: Commit** `feat: stack profile detection and verify command resolution`

---

### Task 7: Workspace clone/update

**Files:**
- Create: `src/workspace/git.ts`
- Modify: runner 在簇处理前 ensureRepo
- Test: `test/unit/git-workspace.test.ts`（可 mock `execFile`；或 skip 无网络）

**Interfaces:**
- `ensureRepo({ workDir, repoUrl, branch, token }): Promise<{ repoPath, headSha }>`
- clone 到 `{workDir}/repos/<safeName>/`；已存在则 fetch + checkout
- HTTPS clone 用 token（注意日志脱敏）

- [ ] **Step 1: mock 单测 ensureRepo 调用 git clone 参数正确**

- [ ] **Step 2: 实现 git.ts**

- [ ] **Step 3: Commit** `feat: ensure local git workspace for clusters`

---

### Task 8: SDK runner 封装（只读 / 可写两种模式）

**Files:**
- Create: `src/agent/sdk-runner.ts`
- Test: `test/unit/sdk-runner-options.test.ts`（测 options 拼装，不真调 API）

**Interfaces:**
- `runAgentSession(input: { cwd, prompt, mode: 'analyze'|'implement', maxTurns, mcpServers?, skillsDir? })`
- analyze：`allowedTools: Read,Glob,Grep,Skill`（+ 只读 MCP）
- implement：上述 + `Edit`，`permissionMode: 'acceptEdits'`
- `settingSources: []` 或仅挂载包内 skills；`env` 注入 ANTHROPIC_*

- [ ] **Step 1: 单测 analyze 模式不含 Edit**

- [ ] **Step 2: 实现 sdk-runner**

- [ ] **Step 3: Commit** `feat: wrap Claude Agent SDK with analyze/implement modes`

---

### Task 9: Analyze 阶段（Localization → RootCause → Plan）+ 双结局分支

**Files:**
- Create: `src/pipeline/analyze.ts`, `src/pipeline/fixability.ts`
- Modify: `runner.ts` 按簇调用；不可修写 unfixed
- Test: `test/unit/fixability.test.ts`；`test/unit/analyze-parse.test.ts`（解析 artifact JSON）

**Interfaces:**
- `analyzeCluster(...): Promise<{ status: 'fixable'|'unfixed', rootCause?, solution?, reason? }>`
- Prompt 要求模型输出/写入符合 `RootCauseArtifact`（含 `fixability` 三态）与 `SolutionArtifact`
- `not_actionable` | `needs_more_context` → **立刻 unfixed 完整说明**，不 Implement
- `fixable` → 进入 Task 10

- [ ] **Step 1: 单测三态门禁**

- [ ] **Step 2: 实现 analyze + 解析容错（ValidationError → unfixed）**

- [ ] **Step 3: Commit** `feat: analyze pipeline with Seer-like fixability gate`

---

### Task 10: Prepare + Implement + Verify + Iterate

**Files:**
- Create: `src/pipeline/prepare.ts`, `src/pipeline/implement.ts`
- Modify: `src/pipeline/verify.ts`（真正 exec）
- Test: `test/unit/verify-exec.test.ts`（mock spawn）；`test/unit/iterate-budget.test.ts`

**Interfaces:**
- `prepareRepo(profile, repoPath): install`
- `implementCluster(...): { changedFiles }` 用 SDK implement 模式；注入 rootCause+solution
- `runVerify(repoPath, plan): { ok, command, logTail }`
- `maxIterate`（默认 3）：失败则把 logTail 回灌再 implement
- 无 test 命令 → unfixed `no_test_command`（**不开 MR**）
- verify 耗尽 → unfixed `verify_failed`

- [ ] **Step 1: 单测 iterate 次数上限**

- [ ] **Step 2: 实现 prepare/implement/verify 串联**

- [ ] **Step 3: Commit** `feat: prepare implement verify iterate with GREEN gate`

---

### Task 11: GitLab Deliver（push + create MR）

**Files:**
- Create: `src/pipeline/deliver.ts`, `src/gitlab/client.ts`
- Test: `test/unit/deliver-branch.test.ts`（mock API）

**Interfaces:**
- `deliverFix({ repoPath, runId, clusterId, title, description, gitlabHost, token }): { mrUrl }`
- 分支：`bugfix/{runDirId}/{clusterId}`
- Orchestrator：`checkout -b` → `add` → `commit` → `push` → GitLab `POST /projects/:id/merge_requests`
- 失败 → unfixed `push_failed`（保留本地分支路径写入 reasonDetail）
- **永不 merge**

- [ ] **Step 1: mock GitLab create MR 单测**

- [ ] **Step 2: 实现 deliver + gitlab client**

- [ ] **Step 3: Commit** `feat: GitLab push and create MR from orchestrator`

---

### Task 12: 汇总 Report 接满 runner（端到端双结局）

**Files:**
- Modify: `src/pipeline/report.ts`, `src/runs/runner.ts`
- Test: `test/integration/runner-dual-outcome.test.ts`（mock analyze/implement/verify/deliver）

**Interfaces:**
- runner 串行处理 clusters，填充 `fixed[]` / `unfixed[]`，写 `report.json`，status=completed
- GET `/v1/runs/:id` 返回完整 report
- summary 计数正确

- [ ] **Step 1: 集成测试：一簇 fixable mock GREEN → fixed；一簇 not_actionable → unfixed**

- [ ] **Step 2: 接满 runner**

- [ ] **Step 3: Commit** `feat: dual-outcome run report for daily batch`

---

### Task 13: 内置 Skills（首批）+ SDK 挂载

**Files:**
- Create: `skills/systematic-debugging/SKILL.md`, `skills/minimal-diff/SKILL.md`, `skills/hierarchical-localization/SKILL.md`, `skills/test-triage/SKILL.md`, `skills/vue-debug/SKILL.md`, `skills/verify-green-gate/SKILL.md`, `skills/typescript-null-safety/SKILL.md`, `skills/patch-review/SKILL.md`
- Modify: `src/skills/manifest.ts`, `sdk-runner.ts`
- Test: `test/unit/skills-manifest.test.ts`

**Interfaces:**
- 包内 skills 目录在 session 中对模型可见；`options.skills.disabled/enabled` 生效
- description 写清何时使用

- [ ] **Step 1: 单测 manifest 列出 ≥6 个 skill**

- [ ] **Step 2: 写入 SKILL.md 并挂载**

- [ ] **Step 3: Commit** `feat: ship builtin skills catalog for selective Skill tool use`

---

### Task 14: MCP 配置加载

**Files:**
- Create: `src/mcp/load-config.ts`
- Modify: `sdk-runner.ts`, `types.ts`（CreateRunRequest.options.mcp）
- Test: `test/unit/mcp-load-config.test.ts`

**Interfaces:**
- 合并优先级：Run options → `{workDir}/.bugfix/mcp.json`
- `${ENV}` 展开；`allowedTools`/`deniedTools` 传入 SDK
- 默认分析阶段 deny 写类工具名（启发式）

- [ ] **Step 1: 单测 env 展开与合并**

- [ ] **Step 2: 实现并接入 runner**

- [ ] **Step 3: Commit** `feat: configurable MCP servers for agent sessions`

---

### Task 15: StorageAdapter stub + README 用法

**Files:**
- Create: `src/storage/adapter.ts`, `src/storage/noop.ts`, `src/storage/http.ts`（best_effort POST report）
- Create: `README.md`
- Test: `test/unit/storage-noop.test.ts`

**Interfaces:**
- `StorageAdapter.syncProgress` / `syncReport`
- README：如何配 Dify、日批流程、环境变量、报告字段说明、与 Seer 差异（全自动双结局）

- [ ] **Step 1: noop 单测**

- [ ] **Step 2: stub http adapter + README**

- [ ] **Step 3: Commit** `docs: README and optional remote storage adapter stub`

---

## 验收清单（MVP Done）

- [ ] `npm test` 全绿
- [ ] `npm run build` && `npm pack --dry-run` 含 `dist/` + `skills/`
- [ ] `npx bugfix-agent --help` / `serve` 可起本地 HTTP
- [ ] `POST /v1/runs` + 轮询可得到 `report.fixed` / `report.unfixed`
- [ ] 不可修簇有 `reasonDetail`，不产生 MR
- [ ] 可修且验证通过的簇有 `mrUrl`（可用 mock/录制或沙箱 GitLab）
- [ ] 文档说明 npm 安装、日批用法与环境变量
- [ ] 无产品级「根因后等待用户」API
- [ ] README 注明：**勿** `npm i --omit=optional`（Agent SDK 平台二进制）

## 后续 Plan（勿塞进本 MVP）

1. LLM 增强聚合 / embedding 簇  
2. 多样本选优 + Reviewer  
3. Electron E2E 可选门闩  
4. StorageAdapter 生产实现与鉴权  
5. GitLab CI → pr_iteration  
6. Dify 官方 Tool OpenAPI 样例仓库  

---

## 执行方式

实现时推荐：`superpowers:subagent-driven-development`，按 Task 1→15 顺序，每 Task 测试通过再 commit。  
若需隔离目录，先走 `using-git-worktrees`。
