> 当前生产契约：0.3.0（2026-11-16）。目录保留原文档路径；旧 Agent 产物版本明确拒绝，请重新生成。

# code-knowledge v0.1

**Producer:** Agent-2 (cartographer) · **Consumer:** Agent-3 only

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | string | `"0.3.0"` |
| `productLine` / `workDir` | string | |
| `partial` | boolean | 探测/匹配不完整仍可校验通过 |
| `generatedAt` | ISO string | |
| `repoRoots[]` | `{ path, gitHead?, fingerprint? }` | 多子仓；`path` 相对 workDir |
| `cartographyProfile` | enum | `electron_node` \| `micro_frontend` \| `device_web` \| `unknown`。由平台入口传入，Agent-2 **不探测** |
| `secondaryHints[]` | string | 含 `enrich=<sdk\|heuristic\|sdk_fallback>; <原因>`，用来判断 Agent-2 到底调用没调用 LLM |
| `techStack` | `{ languages[], frameworks[], notes }` | |
| `architecture` | `{ summary, entryPoints[], modules[] }` | modules: `{ id, path?, role? }` |
| `conventions` | `{ fromClaudeMd[], fromRules[] }` | `fromClaudeMd` 是保留字段，恒为空：CLAUDE.md 只用来判 `codeGraph` / `frameworkId`，正文截取不进产物（文件路径在 `specAtlas.entries`） |
| `boundSkills[]` | string | 本次实际绑定的 cartography skill 名（仓内 / `.bugfix` / `--skills-dir` overlay 在前，包内置在后） |
| `specAtlas` | framework + entries + drDs | `frameworkId` 封闭集或 `unknown`。磁盘有 `.trellis/spec` 时 `entries[]` 追加 `kind=doc_ref` 的目录路径（不抄正文）；Agent-3 按票 Read 命中的 0～2 条 |
| `capabilities` | `{ codeGraph, runtimeVerify }` | |
| `defectCodeMatches[]` | per-ticket soft start | **核心交付** |

### defectCodeMatches[]

| Field | Type | Notes |
|---|---|---|
| `defectId` | string | |
| `clusterId` / `title` | ? | |
| `candidates[]` | `{ repoPath, path, symbol?, why, source }` | 可空 |
| `confidence` | high/medium/low | |
| `gap` | `no_path_token_overlap` \| omit | 空候选且票面词与路径无交集时填写；不是分析失败 |

`source`: `codegraph` \| `grep` \| `heuristic` \| `claude_md`

默认只为 pool ∈ {strict, locatable_only, needs_info} 写匹配。

## 0.3.0 逐票调查交接

defectCodeMatches 每票保存 investigationStatus、searchedScopes、facts、hypotheses、ruledOut、openQuestions、nextChecks、investigationSource。SDK 自述来源固定 model_reported；complete 只代表本轮调查返回且有事实/搜索范围，不代表根因已证明。investigationRuns 保留组范围、来源、缓存键、预算及账单 detail；首组建图与调查，后续组复用地图。runtimeProfile 和 skillDiscovery 不把声明能力/技能选择冒充实测执行。
