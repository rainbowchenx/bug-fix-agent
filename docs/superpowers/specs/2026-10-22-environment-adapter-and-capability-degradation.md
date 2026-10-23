# 环境适配层与能力降级设计

> 基线：`main` @ `550eb7a`（2026-10-22）。
> 前置依据：[缺陷输入形态与来源契约](2026-10-22-defect-input-shape-and-source-contract.md)（`OBS-*` / `INV-*` / `C-*` / `GAP-F*`）、[目标流水线设计](2026-10-22-target-pipeline-design.md)（`S0..S10` / `CLS-*` / `LOC-*` / `GATE-*` / `DEL-*`）。
> 定位：回答「业务环境异构、无法穷举适配」时的工程出路。本文定义**适配层的契约（`EnvironmentProfile`）、能力派生（`capabilities`）与降级阶梯（`L0..L3`）**，并给出对主流程的增量修改。**不含实现**。
> 一句话立场：**不追求全适配，追求可度量的降级。**
>
> **⚠️ 产品边界变更**：本产品最终**只做分析、不出 MR**（见 [报告型分析 Agent 设计](2026-10-23-report-agent-design.md)）。因此本文中的 `Probe` 执行、dev-server 托管、多仓交付（`ENV-9`）**属下游职责**；本产品只消费 `profile.localization` 与 `profile.capabilities` 用于分析阶段的降级判定（`L0..L3` 仍成立：`L1` 只能出报告、不能给运行时验证方案）。

---

## 0. 结论先行

| 判断 | 内容 |
|---|---|
| 业务异构能否穷举 | ❌ 不能。自定规则、外部定位平台、无单测、前后端双仓、私域依赖、私有网关…… 不可能在核心代码里逐一适配 |
| 正确解法 | ✅ 前置**适配层**，产出可校验的**契约文件**（`EnvironmentProfile`），核心只读契约 |
| 契约要回答什么 | **三件事**：① 怎么复现 ② 怎么观察 ③ 怎么判定 |
| 如何避免"适配不了就全废" | 用 `capabilities` 派生 + **四级降级阶梯**（完整 / 部分 / patch-only / 不可用） |
| 最重要的参照 | **SWE-bench**：验证契约是**数据**不是代码；且**环境不完整时退化为 patch-only 仍然有价值** |
| 最划算的一处改动 | 把 `verify` 从「一条命令」泛化为**探针列表**（`Probe[]`），一次解决无单测 / UI 验证 / 跨仓联动 |
| 真正的架构变更 | **一簇 = 一仓** 的假设要打破（`cluster.repoSet`），双仓联合启动会同时影响 4 处 |

---

## 1. 问题：业务异构的具体形态

| # | 异构点 | 具体表现 | 对核心的冲击 |
|---|---|---|---|
| 1 | **自定业务规则** | "禁止改 A 目录"、"必须走统一请求封装"、"i18n 必须四语齐全" | 现在的 `policies` 只有 scope lock 一处，无法表达可校验规则 |
| 2 | **外部平台提供定位数据** | 监控平台（Sentry 类）、用户行为回放、调用链追踪 | 核心不认识这些平台，且不应引入运行时依赖 |
| 3 | **没有单测** | 只有手工测试 | `test` 命令为空 → 现有实现直接 `no_test_command` 拒绝交付 |
| 4 | **前后端双仓联合启动** | 单仓起不来，必须 FE + BE 一起跑 | 打破「一簇 = 一仓 = 一 worktree = 一 MR」 |
| 5 | **私域依赖 / 私有网关** | npm 私服、内网 registry、VPN | 环境准备阶段就失败 |
| 6 | **服务编排复杂** | 需要 DB / Redis / MQ / mock server | 无"多服务就绪"概念 |
| 7 | **验收标准是业务口径** | "导出的 Excel 里第 3 列应为两位小数" | 只能用探针表达，无法用单测表达 |
| 8 | **规范文档分散** | 设计稿、接口文档、编码规范各在别的系统 | 无法统一注入 |

**结论**：这些差异不应由核心代码分支覆盖，而应被压缩成**一份声明式契约**。

---

## 2. 参考实现：SWE-bench 如何把异构收敛

### 2.1 instance 字段

| 字段 | 作用 |
|---|---|
| `instance_id` / `repo` | 唯一标识 + 代码仓 |
| `base_commit` | **钉死代码版本** |
| `problem_statement` / `hints_text` | **自然语言描述，无堆栈**（与我们的缺陷单同类） |
| `patch` | gold patch（评测用，不给模型） |
| `test_patch` | 官方测试补丁（验证用，不给模型） |
| `FAIL_TO_PASS` / `PASS_TO_PASS` | **验收契约 + 回归契约** |
| `version` / `environment_setup_commit` | **环境钉死** |

### 2.2 三个可抄的设计决策

| 决策 | SWE-bench 的做法 | 对我们的映射 |
|---|---|---|
| **版本钉死** | `repo@base_commit` + `version` | `workDir` 必须钉在可复现基线（`baseSha`），不能用"当前 main" |
| **验证契约外置** | `FAIL_TO_PASS` / `PASS_TO_PASS` 是**数据** | 千差万别的项目共用同一套判定器 → 这就是适配层 |
| **环境容器化** | 每 instance 一个镜像，install spec 也是**数据** | profile 是**数据文件**，不是代码分支 |

### 2.3 最反直觉但最有用的一点

SWE-bench 原始设定里，**模型只输出 patch，不跑测试**。评分在 harness 侧完成（容器内应用 `test_patch`，跑 `FAIL_TO_PASS` + `PASS_TO_PASS`）。

> **`ENV-1`** 「能不能自己验证」与「能不能产出正确修复」是两件事。
> 环境完备只影响**迭代质量**与**自证能力**；不全时退化为 **patch-only**，仍然有交付价值。

### 2.4 附：UI 方向已有先例

`SWE-bench Multimodal` 针对 JavaScript 前端仓库，**issue 中带截图**；`Multi-SWE-bench` 覆盖多语言。说明"缺陷单带图、靠图验收"是可研究方向，但其成立前提依旧是**契约外置 + 版本钉死**。

---

## 3. 契约设计：`EnvironmentProfile`

### 3.1 核心抽象：三问

```
① 怎么复现？  workspace  — 单仓/多仓、bootstrap、services（端口/就绪探测/依赖）
② 怎么观察？  observation — probes（command/http/file/db/browser/log）
③ 怎么判定？  acceptance  — test-suite / targeted-test / probe / visual / manual
```

**三问有答案 → 进流水线；缺哪一项 → 按缺口降级**（`ENV-2`）。

### 3.2 结构

```ts
interface EnvironmentProfile {
  profileId: string;
  projectId: string;
  version: string;
  source: "auto" | "manual" | "platform";
  origin: string;                       // 谁产出（人 / 适配会话 / 平台）

  workspace: {
    kind: "single-repo" | "multi-repo";
    repos: Array<{ key: string; repoUrl: string; branch: string; subPath?: string }>;
    bootstrap?: Array<{ command: string; cwd: string; timeoutMs?: number }>;   // 多仓联合启动
    services?: Array<{
      name: string; command: string; port: number;
      readyPath?: string; dependsOn?: string[];
    }>;
  };

  observation: {                        // ② 怎么观察
    kinds: Array<"command" | "http" | "file" | "db" | "browser" | "log">;
    probes: Probe[];
  };

  acceptance: {                         // ③ 怎么判定
    kind: "test-suite" | "targeted-test" | "probe" | "visual" | "manual";
    tests?: string[];                   // 目标用例（FAIL_TO_PASS 的本地化）
    probes?: Probe[];
    visual?: { viewport: Viewport; baselineDir?: string };
  };

  localization: {                       // 定位增强（解决"不能盲 grep"）
    moduleMapping: Record<string, string>;        // 缺陷模块 → 目录/包
    glossary: Record<string, string[]>;           // 业务词 → 代码符号（LOC-L2）
    i18n?: { dirs: string[]; locales: string[] };
    routes?: string[];
    versionTags?: string[];
    externalHints?: Array<{ provider: string; url?: string; query: string }>;
  };

  policies: {                           // 业务规则（硬约束，不是提示）
    forbiddenPaths: string[];
    codingRules: string[];
    requiredReviewers?: string[];
    secretScan: boolean;
  };

  credentials: { ref: string };         // 只存引用，不落明文

  capabilities: Capabilities;           // ★ 由上面派生，主干只读这个
}
```

### 3.3 派生规则（`ENV-3`）

| capability | 判定条件 |
|---|---|
| `canRunTests` | `acceptance.kind ∈ {test-suite, targeted-test}` 且 `tests.length > 0`，或 `probe` 中存在 `kind=command` |
| `canRenderUI` | `services` 非空 且 存在 `kind=browser` 的 probe |
| `canLogin` | `uiVerify.login`（或 `credentials.ref` 指向可解析凭据）存在 |
| `multiRepo` | `workspace.kind === "multi-repo"` 且 `repos.length > 1` |
| `canReproduce` | `canRunTests || canRenderUI || probes.some(p => p.kind ∈ {http,file,db})` |
| `canVerify` | `acceptance.kind !== "manual"` 且（`canRunTests || canRenderUI || canReproduce`） |

**关键：派生是纯函数。** profile 手写有误时，`capabilities` 会暴露矛盾（例如声明 `test-suite` 但 `tests` 为空 → `canRunTests=false`）。

---

## 4. 能力降级阶梯（`ENV-4`）

| 级别 | 满足条件 | 可做的事 | 交付形态 |
|---|---|---|---|
| **L3 完整** | `canVerify && canRunTests`（+ UI 类需 `canRenderUI`） | 全流程：RED→改码→GREEN；UI 目视 | 逻辑类正常 MR / UI 类 Draft MR |
| **L2 部分** | `canReproduce` 但无测试（只有探针/截图） | 无 RED，只能前后对比 | **Draft MR + 人工必审** |
| **L1 最低** | 只有仓库（`capabilities` 全 false） | 读代码 + 出 patch（**SWE-bench 模式**） | **不开 MR，出 `patch.diff` + 报告** |
| **L0 不可用** | 仓库不可得 / 基线不可得 | — | `unfixed` |

> **`ENV-5`** 降级是**逐簇**的，不是整批的。同一批里允许"这条 L3、那条 L1"。
> **`ENV-6`** L1 模式必须显式标注在报告里（`deliveryMode: "patch_only"`），不允许伪装成 MR 交付。

---

## 5. 四类异构的落点

### 5.1 自定业务规则 → `policies`（分软硬两档）

| 档 | 例子 | 执行点 |
|---|---|---|
| **硬约束（可机器校验）** | 禁止改 `src/legacy/**`；必须经 `utils/request` 发请求；i18n 四语必须齐全 | `scope-lock` / `static-check` / `review` 三处**实际执行**，违反即 `unfixed` |
| **软约束（仅提示）** | 命名风格、注释要求 | 注入 prompt（`codingRules`），不阻断 |

> 现状：只有 scope lock 一处硬约束，且只校验"文件白名单"。`policies.forbiddenPaths` 与"必须走某封装"这类规则**完全缺失**。

### 5.2 外部定位平台 → 声明式 provider + 落地文件

```jsonc
"externalHints": [
  { "provider": "sentry", "url": "https://.../issues?query={fingerprint}", "query": "{defectId}" }
]
```

**约束（`ENV-7`）**：外部数据由**适配阶段一次性抓取并落地为本地文件**（如 `{runDir}/hints/{defectId}.json`），核心只读文件。
理由：可复现、无运行时依赖、离线可重跑、不会因平台不可用阻断主流程。

### 5.3 没有单测 → 探针化（`Probe`）

```ts
type Probe =
  | { kind: "command"; command: string; cwd?: string; expectExitCode?: number; expectStdout?: string }
  | { kind: "http";    method: string; url: string; body?: unknown;
      expect: { status?: number; jsonPath?: Record<string, unknown>; contains?: string } }
  | { kind: "file";    path: string; exists?: boolean; contains?: string; matches?: string }
  | { kind: "db";      connection: string; query: string; expectRows?: number; expectValue?: unknown }
  | { kind: "browser"; steps: BrowserStep[]; assert: { selector?: string; text?: string;
      screenshotCompare?: { baseline: string; region?: Rect } } }
  | { kind: "log";     path: string; present?: string[]; absent?: string[] };
```

> **`ENV-8`** 探针替代「一条 shell 命令」是本次设计里性价比最高的一处改动，一次解决三个问题：
> 无单测（http/file/db 给客观信号）、UI 类（browser + 截图）、跨仓联动（http 打前端，前端调后端）。

**实现影响**：`pipeline/verify.ts` 从 `runVerify(command)` 变为 `runProbes(Probe[]) → ProbeResult[]`，聚合规则：
`ok = 所有 expect 命中`；失败时输出**逐探针**结果（便于回灌 iterate）。

### 5.4 前后端双仓 → `repro unit`

现有假设被打破的四处：

| # | 现状 | 需要变成 |
|---|---|---|
| 1 | `ClusterSchema.repoUrl`（单值，必填） | `cluster.repoSet: Array<{ repoKey, repoUrl, subPath?, baseSha, worktreePath }>` |
| 2 | `ensureRepo()` 一簇一 worktree | 一簇 N worktree（每仓一个），统一 baseSha 记录 |
| 3 | `checkScopeLock()` 单仓相对路径白名单 | 按 `repoKey` 分组校验 |
| 4 | `deliverFix()` 单分支单 MR | 逐仓 commit/push/MR → 报告给 `mrGroupId` 归组 |

> **`ENV-9`** 多仓交付必须**原子化呈现**：报告里以 `mrGroupId` 汇总，任一仓失败则该簇整体视为 `unfixed`（不允许"前端改了后端没改"的半成品交付）。

---

## 6. 适配器本身的形态

| 形态 | 做法 | 成本 | 适用 |
|---|---|---|---|
| **A. 人工填 profile** | 提供 `env-profile.json` 模板 + zod 校验器 | 低，可控 | 首批项目（推荐起点） |
| **B. 适配会话（agent）** | 勘探仓库：找 install/test 脚本、i18n 目录、路由、试起服务 → 产出 profile 草案 | 中 | 需要铺量 |
| **C. 平台对接** | 外部平台按 provider 接口供数据 | 高 | 有平台能力的团队 |

### 6.1 四条硬约束（否则会失控）

| # | 约束 | 理由 |
|---|---|---|
| 1 | 输出必须 **schema 校验**，不合格直接拒绝 | 防半成品 profile 流入主干 |
| 2 | 适配失败 → **降级**，不是中止整批 | 对齐 `ENV-5` |
| 3 | profile **可缓存复用**（键 `projectId + version`） | 一批 6 条缺陷只适配一次 |
| 4 | profile 是**数据文件**，可人工审阅/覆盖 | 可持续维护的前提（对齐 SWE-bench 的 install spec） |

---

## 7. 对主流程的增量修改

在 `target-pipeline-design.md` 的 `S0..S10` 上做三处增量：

```
[S-1] 环境适配（Agent 外 / 独立会话）
      → EnvironmentProfile（schema 校验 + capabilities 派生 + 缓存）
   ↓
[S0] 环境预检 = 读 profile.capabilities（不再自己探测）
   ↓
   主干按 capabilities 逐簇降级
   ↓
[S7] 验证 = 跑一组探针（Probe[]），而非一条命令
   ↓
[S9] 交付 = 单仓一 MR / 多仓 mrGroupId 归组；L1 出 patch 不开 MR
```

### 7.1 矩阵新增一列「最低能力要求」

| 类型 | 最低 capability | 达不到时 |
|---|---|---|
| `CLS-1..3` 逻辑/契约 | `canRunTests` 或可写探针 | L2 → Draft；L1 → patch-only |
| `CLS-4` i18n | 仅需仓库（静态断言 key） | 通常总能满足 ✅ |
| `CLS-5` UI | `canRenderUI` + `canLogin` | L2 → 人工；L1 → patch-only + 报告 |

> **反直觉但重要**：`CLS-4`（i18n）是**最容易做的一类**——只需仓库即可客观验证（key 齐全性），不依赖任何环境能力。**应优先落地这一类。**

---

## 8. 与现有实现的差量（增量部分）

| 位置 | 改动 | 关联 |
|---|---|---|
| 新增 `adapters/env-profile/` | schema + zod 校验 + `capabilities` 派生纯函数 + 缓存读写 | `ENV-3`、§6 |
| 新增 `pipeline/probes.ts` | `Probe` 执行器（command/http/file/db/browser/log）+ 结果聚合 | `ENV-8` |
| `pipeline/verify.ts` | 由 `runVerify(command)` 改为 `runProbes(probes)`；保留命令兼容层 | `ENV-8` |
| `types.ts` | `cluster.repoSet`；`deliveryMode: "mr" \| "draft_mr" \| "patch_only"`；`capabilities` 透传 | `ENV-9` |
| `workspace/git.ts` | 多仓 `ensureRepo`（返回 worktree 集合） | §5.4 |
| `pipeline/scope-lock.ts` | 按 `repoKey` 分组校验 + `policies.forbiddenPaths` | §5.1 |
| `pipeline/deliver.ts` | 多仓逐仓交付 + `mrGroupId`；L1 输出 `patch.diff` | `ENV-9`、`ENV-6` |
| `pipeline/prefilter.ts`（P0 已计划） | 预检改为读 `capabilities` 而非自行探测 | §7 |

---

## 9. 待决策项（续 `DEC-12..19`）

| # | 决策 | 影响 | 建议 |
|---|---|---|---|
| `DEC-20` | **多仓是否进 v1**（`cluster.repoSet`） | 决定 schema 现在改还是留空 | 若首批存在 FE+BE 场景则必须进；否则先留 `repoSet: [single]` 以统一结构 |
| `DEC-21` | profile 产出方式（A 人工 / B 会话 / C 平台） | 决定适配层工作量 | 先 A，验证 schema 后再上 B |
| `DEC-22` | profile 存放位置与缓存键 | 复用性 | `projectId + version`，落在 `workDir` 外的注册目录 |
| `DEC-23` | 探针是否**替代** verify 命令，还是**并存** | 改动量 vs 兼容性 | 并存（命令探针 = `kind=command`），逐步迁移 |

---

## 10. 风险与边界

| 风险 | 表现 | 缓解 |
|---|---|---|
| profile 写得过细 | 每条缺陷都要改 profile，维护崩溃 | profile 只描述**项目级**能力，簇级差异靠 `moduleMapping` |
| profile 与真实环境漂移 | 声明 `canRunTests` 实际跑不起来 | `S0` 做一次**轻量冒烟**（跑 1 个最小探针），失败即降级 |
| 探针本身脆弱 | 硬编码 URL/选择器 | 探针失败归类为 `env_verify_failed`，不计入 iterate 预算 |
| 多仓交付半成品 | 前端改了后端没改 | `ENV-9` 原子化：任一仓失败 → 整簇 `unfixed` |
| L1 patch-only 被误当成交付 | 用户以为已经修好 | 报告中 `deliveryMode` 显式 + 不写 `mrUrl` |
| 适配层变成第二个核心 | 规则越加越多 | 硬约束只允许"可机器校验"的三类（路径/调用封装/i18n 完整性），其余入 prompt |

---

## 附录 A：`EnvironmentProfile` 最小示例

```jsonc
{
  "profileId": "hcp-inspection-v2.2",
  "projectId": "PJ14PD20250909046",
  "version": "V200R324C001",
  "source": "manual",
  "origin": "项目组填写",
  "workspace": {
    "kind": "multi-repo",
    "repos": [
      { "key": "web", "repoUrl": "git@…/hcp-web.git", "branch": "release/2.2", "subPath": "packages/inspection" },
      { "key": "api", "repoUrl": "git@…/hcp-api.git", "branch": "release/2.2" }
    ],
    "bootstrap": [{ "command": "pnpm install", "cwd": "." }],
    "services": [
      { "name": "web", "command": "pnpm dev", "port": 5173, "readyPath": "/" },
      { "name": "api", "command": "npm run start:dev", "port": 8080, "readyPath": "/health" }
    ]
  },
  "observation": {
    "kinds": ["browser", "http"],
    "probes": [{ "kind": "browser", "steps": [], "assert": {} }]
  },
  "acceptance": {
    "kind": "visual",
    "visual": { "viewport": { "width": 1440, "height": 900, "deviceScaleFactor": 1, "zoom": 100 } }
  },
  "localization": {
    "moduleMapping": {
      "智能巡检_任务": "HikCentral Professional/WEB/智能巡检",
      "智能巡检_报表": "HikCentral Professional/WEB/智能巡检"
    },
    "glossary": { "巡检": ["inspection"], "字符叠加": ["OSD", "overlay"] },
    "i18n": { "dirs": ["src/locales"], "locales": ["zh-CN", "en-US", "ja-JP", "no-NO"] },
    "routes": ["src/router/inspection.ts"],
    "versionTags": ["v2.2.0"]
  },
  "policies": {
    "forbiddenPaths": ["src/legacy/**"],
    "codingRules": ["统一走 utils/request 发请求"],
    "secretScan": true
  },
  "credentials": { "ref": "env:HCP_TEST_LOGIN" },
  "capabilities": {
    "canRunTests": false, "canRenderUI": true, "canLogin": true,
    "multiRepo": true, "canReproduce": true, "canVerify": true
  }
}
```

> 该例对应 `L3`（但无单测）→ UI 类走 Draft MR，逻辑类只能 L2（探针/Draft）。

## 附录 B：三份 profile 样例的验证意义

| 样例 | 覆盖什么 | 用途 |
|---|---|---|
| `配套-交通` | 单仓 / 系统测试 / 无 expected 图 / UI 为主 | 验证 `L2` 降级路径 |
| `hcp巡检` | 单仓（或双仓）/ 软件集成测试 / 有设计稿 / 含 SCA | 验证 `canRenderUI` + 多语言断言 |
| 一个 SWE-bench instance | 单仓 / `FAIL_TO_PASS` / 有单测 / 无 UI | 验证 `L3` 完整路径与 `acceptance=tests` |

## 附录 C：`capabilities` → 类型可达性总表

| capability 组合 | `CLS-1/2/3` | `CLS-4` | `CLS-5` | 交付 |
|---|---|---|---|---|
| 全部 true | ✅ L3 | ✅ L3 | ✅ L3 | 正常 / Draft |
| `canRunTests` false，`canReproduce` true | ⚠️ L2 | ✅ L3 | ⚠️ L2 | Draft |
| 仅仓库 | ⚠️ L1 | ✅ L3 | ❌ L1 出 patch | patch-only |
| 仓库不可得 | ❌ L0 | ❌ L0 | ❌ L0 | unfixed |
