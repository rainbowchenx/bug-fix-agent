# 三 Agent 架构探讨备忘（草稿）

> 日期：2026-10-30  
> 状态：**探讨中 / 非正式规格**——只记录共识方向与待拍板点，**不启动实现**。  
> 相关已有文档：
> - [报告型分析 Agent 设计](2026-10-23-report-agent-design.md)（只分析、出报告）
> - [报告型分析 Agent 决策备忘](2026-10-23-report-agent-decision-memo.md)
> - [目标流水线设计](2026-10-22-target-pipeline-design.md)
> - [缺陷单多轮筛选与分簇设计](2026-10-30-defect-screen-cluster-design.md)（偏 Agent-1 漏斗）

---

## 0. 探讨结论（当前）

| 项 | 当前倾向 |
|---|---|
| 整体切分 | **三个独立 Agent**，用结构化 artifact 衔接，不传原始对话 |
| Agent-1 | **能力边界**含拉取+筛选+分簇；运行时倾向 **Skill + 规则管线**，不必独立长会话 Agent（见 §2.5） |
| 拉取 | **纳入范围**，与后续步骤**解耦**：`IngestAdapter`（**MCP 为准**，爬虫为备）；产出 `raw-defects` 再进蒸馏 |
| Agent-2 | 持 `defect-batch` 通读指定仓；三形态（electron/微前端/设备 Web）；CodeGraph 主查找；产出含缺陷匹配的 `code-knowledge` |
| Agent-3 | 消费 ①+② → 定位 / 根因 / 修复方案 → 可行动与不可行动报告 |
| Orchestrator | 仍为确定性代码；三 Agent 是可注入阶段，不是互相聊天的 chatbot |
| 产品边界 | 与 10-23 一致倾向：**本产品止于分析报告**；改码/MR 留给下游（待与「可修/不可修」文案对齐） |
| SDD | **框架无关**；不以 OpenSpec / Superpowers / Trellis 等任一品牌为准 |
| Agent-2 skills | 支持额外注入；市场候选已调研，待选型后精选移植 |

---

## 1. 总览

```text
┌─ Agent-1 Defect Ingest ─────────────────────────────┐
│ 拉取 → 清洗/蒸馏 → 规则筛选 → 多层分簇               │
│ 产出: defect-batch（结构化）                         │
└──────────────────────────┬──────────────────────────┘
                           │
┌─ Agent-2 Code Cartographer ─────────────────────────┐
│ 指定目录只读通读 + .claude 发现 + cartography skills │
│ 产出: code-knowledge（可按 baseSha 缓存）            │
└──────────────────────────┬──────────────────────────┘
                           │ ① + ②
┌─ Agent-3 Defect Analyst ────────────────────────────┐
│ Localization → RootCause → ProposedFix               │
│ 产出: analysis-report（可行动 / 暂缓 / 非代码等）    │
└─────────────────────────────────────────────────────┘
```

原则：

1. Agent 之间**只传落盘 artifact**（zod 校验），不传会话 transcript。  
2. 成本重心在 Agent-3；① 以规则为主，② 半规则 + 缓存。  
3. 全自动一次跑完；可轮询进度，**不设人机审批断点**（延续现有产品约束）。  
4. 与 [缺陷筛选分簇设计](2026-10-30-defect-screen-cluster-design.md) 的关系：该文细化 Agent-1 的漏斗语义；本文管三 Agent 边界与衔接。

---

## 2. Agent-1：缺陷蒸馏 / 筛选 / 分簇

### 2.1 职责

| 做 | 不做 |
|---|---|
| **拉取**（见 §2.2，与后续解耦） | 通读业务源码 |
| 蒸馏描述模板、清洗、模块/标题括注取值 | 根因与改码 |
| 规则硬分流（CVE / 端侧 / 偶现 / 信息过薄等） | 缺陷平台**写**操作（关单等） |
| 三层分簇（模块→标题括注→AI 意图）+ 排序 | 把筛池规则交给模型自由发挥 |

### 2.2 拉取：纳入范围，与后续步骤分开

| 项 | 约定 |
|---|---|
| 是否纳入 | **是**（产品能力边界属于「缺陷批次准备」） |
| 形态 | 两种：`mcp`（**当前为准**）/ `crawler`（手动爬虫备援） |
| 解耦 | 独立阶段 **Ingest**，唯一产物 `raw-defects.json`（或等价）；蒸馏/筛选/分簇**只读该产物**，不直连平台 |
| 切换 | `ingest.source = mcp \| crawler \| preloaded`；MCP 不可用时可降级 crawler/预置文件，不改下游契约 |
| 凭据 | 环境变量 / MCP 配置；不进缺陷正文、不进 skill 正文 |

```text
IngestAdapter.mcp      ──┐
IngestAdapter.crawler  ──┼──► raw-defects ──► 蒸馏 → 筛选 → 分簇 → defect-batch
preloaded file         ──┘         ▲
                                   │ 下游禁止绕过此边界回查平台
```

Orchestrator **确定性调用** MCP 白名单工具拉单（推荐）；不宜把「有没有拉全」完全交给模型临场发挥。Skill 可描述「何时用哪个 MCP、字段如何映射」，但拉全与落盘由适配器/编排保证。

### 2.3 分簇层次（已讨论修订）

- **L1** `测试模块`（规则归一；禁用 `所属模块`）  
- **L2** 标题 `【】` / `[]`（规则；无则 `_untagged`）  
- **L3** 缺陷意图（**AI 意图识别**；表字段 `type` 仅先验）  

筛池（R0–R3）不含 AI。细则以 [缺陷筛选分簇设计](2026-10-30-defect-screen-cluster-design.md) 为准。

### 2.4 处理流程（端到端）

```text
【输入】productLine / α|β / ingest 配置（mcp|crawler|preloaded）/ 可选 intent 配置
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
                           ▼ 仅 strict
┌─ C. 三层分簇 ─────────────────────────────────────────┐
│  L1/L2 规则 → L3 AI 意图 → R5 兜底 → R6 排序           │
└──────────────────────────┬────────────────────────────┘
                           ▼
【输出 · defect-batch】→ Agent-2 / Agent-3
```

| 阶段 | LLM？ | 产物要点 |
|---|---|---|
| I Ingest | 否（MCP/爬虫 I/O） | `raw-defects` |
| A 蒸馏 | 否 | `DefectDigest` |
| B 筛选 | 否 | `pool` / `reasonCode` / `expectQuality` |
| C L1–L2 | 否 | `testModule` / `titleTag` |
| C L3 | **是**（意图） | `intent` / `intentSource` / `intentConfidence` |
| C R5–R6 | 否 | 终态簇 + 优先级 |

### 2.5 形态分析：独立 Agent vs Skill

**判断（探讨结论）**：所谓「Agent-1」更适合作为**能力边界 / 批次准备管线**，而不是再挂一个与 Agent-2/3 对等的长会话自主 Agent。

| 步骤 | 本质 | 更合适的载体 |
|---|---|---|
| Ingest（MCP/爬虫） | I/O 适配 | `IngestAdapter` + MCP 工具；Skill 只写用法与字段映射 |
| 蒸馏 / R0–R3 / L1–L2 / R5–R6 | 可复算规则 | **代码管线**（单测 + funnel 回归）；不宜靠模型「照 skill 手跑」 |
| L3 意图 | 短推理 | 管线内一次批处理 LLM，或由宿主会话按 skill 触发分类 |

**为什么不必单独编排一个 Agent-1 进程/会话**

1. 主路径 **0 LLM**，硬门禁与漏斗复算是代码问题，不是对话问题。  
2. 拉取已有 **MCP**；再包一层「拉单 Agent」只增加失败面（漏拉、重复拉、字段漂移）。  
3. 与现有设计一致：Skills = 流程知识，MCP = 工具，Orchestrator = 门禁（见原规格 §8/§9）。  
4. 「三 Agent」仍可作**产品叙事**（批次准备 / 通读 / 分析）；实现上 Agent-1 = **一条 skill 声明的 SOP + 确定性管线**，由总编排或日批 job 调用。

**Skill 适合承担什么**

- 名为如 `defect-batch-prepare` 的 skill：声明触发条件、ingest 选择（mcp 优先）、阶段顺序、产物路径、`defect-batch` 契约、禁止事项（不改码、不关单、筛池不用模型瞎判）。  
- 宿主（日批 runner / 外层 agent）`Skill` 加载后，按 SOP **调用管线入口**（脚本/库 API），而不是逐步 Raw 读 Excel 假装漏斗。

**Skill 不能单独承担什么**

- 五线正则与 profile 的权威实现（应在 `_stage1-rules` → 代码）。  
- MCP 拉全、重试、分页、幂等落盘。  
- funnel/clusters 与 α/β 分母的回归验收。

**推荐落地形状**

```text
defect-batch-prepare/SKILL.md     ← 给人/宿主 agent 的 SOP
src/ingest/{mcp,crawler}.ts       ← 拉取适配，产出 raw-defects
src/pipeline/{distill,screen,cluster-*}  ← 规则管线
（可选）intent 批处理一次 LLM
→ defect-batch.json               ← 唯一交给下游的批次契约
```

相对「三个对等 Agent」：Agent-2 / Agent-3 仍可能是真会话（通读、分析）；Agent-1 降为 **Prepare Skill + Pipeline**。

### 2.6 拍板状态

- [x] 拉取纳入；MCP 为准、爬虫为备；与后续解耦（`raw-defects`）  
- [x] 分簇 L1 测试模块 → L2 标题括注 → L3 AI 意图；筛池纯规则  
- [x] 运行时 = **Skill + 规则管线**，不作独立长会话 Agent（2026-11-01 确认）  
- [ ] L3 意图封闭枚举终版（实现前补）  
- [ ] MCP 工具名/字段映射的具体契约（按实际缺陷 MCP 补）  
- [ ] 对外报告「可修/不可修」vs `confidence` + `suggestedAction`（见 §4，偏 Agent-3）

---

## 3. Agent-2：代码通读（Code Cartographer）

### 3.1 职责与输入

对用户指定目录（git 仓）做只读理解，产出可共享的 `code-knowledge`，供 Agent-3 与后续 run 复用。

**输入（相对初稿补充）**：

| 输入 | 说明 |
|---|---|
| `workDir` / 仓路径 | 用户指定代码目录 |
| **上一轮 `defect-batch`** | 持有已分类的**全部**缺陷（至少标题；建议带 clusterId / testModule / titleTag / intent） |
| 可选 extras | 额外 cartography skills、显式 `specPaths` |

目的不只是「画仓库地图」，而是同时完成：

1. **技术架构 / 技术栈**（见 §3.2 三种形态）  
2. **已绑定 skill**、**已使用 SDD**、**开发约定**（`.claude` 发现总线）  
3. **需求文档 DR/DS 位置**（如有；框架无关探测 + 路径收录）  
4. **缺陷 ↔ 代码匹配**（用标题/簇键 + CodeGraph 快速定位候选）  

### 3.2 业务线代码三种形态（初步框架，待样本特化）

> **状态**：先给通读**分析框架**；各业务示例仓到位后再填探测指纹、目录约定与 skill 条件暴露。  
> 与旧「install/verify Stack Profile」正交：此处只服务**理解与匹配**，不假设起服务 / 跑测。

通读共用骨架（三形态都走）：

```text
1. 读 CLAUDE.md / .claude → 约定、skills、SDD、CodeGraph 用法
2. 判 primaryProfile（可带 secondaryHints）
3. 按形态清单填 architecture / techStack / modules
4. 收 DR/DS 与 spec 绑定
5. 对 ≤~30 条缺陷逐条 CodeGraph 匹配 → defectCodeMatches
```

#### 粗探测信号（初版，非正式指纹）

| Profile | 正向信号（示例） | 负向/注意 |
|---|---|---|
| `electron_node` | 依赖 `electron`；`main`/`preload`；electron-builder / electron-vite；双进程目录 | 纯 Node 库无 UI 时仍可归此类「Node 后端」子型 |
| `micro_frontend` | `single-spa`；根应用注册表；多 `apps/`/`packages/*` 子应用入口 | 与 monorepo 库仓区分：看是否有 spa 注册/导入映射 |
| `device_web` | 设备/嵌入语义（原生桥、设备 SDK、固定分辨率壳）；弱桌面路由假设 | 技术栈仍可能是 Vue/React——**形态看嵌入约束，不看 UI 框架名** |

命中多个 → `primaryProfile` + `secondaryHints[]`，不互斥丢信息。`unknown` 时仍出通用地图 + 匹配，置信度下调。

#### A. `electron_node`（Electron 全栈客户端 / Node 后端）

| 分析维 | 要回答的问题 | 落盘提示 |
|---|---|---|
| 进程边界 | 主进程 / 渲染 / preload 各自入口？ | `modules[].role = main\|renderer\|preload\|node_service` |
| IPC 面 | 哪些 channel / invoke？谁暴露给渲染？ | `architecture.ipcSurface[]` |
| 窗口与路由 | BrowserWindow 创建点；渲染侧路由/状态 | `entryPoints` + 页面模块 |
| 打包与环境 | 开发/生产差异、额外 Node 服务 | `techStack.notes` |
| 缺陷匹配偏置 | 标题含「闪退/托盘/升级/IPC」→ 主进程；纯 UI 文案 → 渲染 | 写入 `candidates[].why` |

可挂仓内/内置只读 skill 方向：进程边界、Node 服务定位（样本到了再钉 skill id）。

#### B. `micro_frontend`（自研微前端 · single-spa）

| 分析维 | 要回答的问题 | 落盘提示 |
|---|---|---|
| 基座 | 根配置在哪？如何 `registerApplication`？ | `architecture.shell` |
| 子应用目录 | 每个子应用入口、路由前缀、部署名 | `modules[]` 一应用一模块 |
| 共享层 | 公共依赖、工具包、样式/权限 | `modules[].shared` |
| 跨应用通信 | props / 事件总线 / 全局状态 | `architecture.crossApp` |
| 缺陷匹配偏置 | `测试模块`/标题括注 → 子应用名；先锁定子应用再 CodeGraph | `moduleHint` 优先 |

样本特化时重点：公司注册表文件名、子应用命名与测试模块字段的对照表。

#### C. `device_web`（设备嵌入 Web）

| 分析维 | 要回答的问题 | 落盘提示 |
|---|---|---|
| 嵌入宿主 | 如何被设备壳加载？URL/本地资源？ | `architecture.embedHost` |
| 设备桥 | JSBridge / 原生 API / 插件列表 | `architecture.deviceBridge[]` |
| 运行约束 | 离线、分辨率、浏览器内核版本、权限 | `techStack.constraints` |
| 页面结构 | 预览/回放/设置等设备场景入口 | `modules[]` 按设备功能面 |
| 缺陷匹配偏置 | 「预览/云台/码流/OSD」等设备词 → 对应模块 + 桥层 | 区分「纯 H5」vs「桥调用失败」 |

样本特化时重点：各设备线桥接口文档位置、与 DR/DS 的对应。

#### 与缺陷匹配的共用规则（已定）

- **按条**匹配；批次预估 ≤30。  
- 查询词：标题 + titleTag + testModule +（可选）intent。  
- 形态只影响**优先搜哪类模块/边界**，不改变按条粒度。

### 3.3 CodeGraph（默认能力）

**共识**：

- CodeGraph 在**用户仓库**内。  
- **如何调用以该仓 `CLAUDE.md`（及其指向）为准**——本产品**不另写**发现协议、入口白名单或特殊探测逻辑。  
- Agent-2 通读时必读 `CLAUDE.md`；按其说明使用 CodeGraph；未说明或调用失败再降级 Glob/Grep/Read，并记 `capabilities.codeGraph=false`（匹配置信度上限下调）。

### 3.4 产物形态（探讨修订）

```jsonc
{
  "baseSha": "…",
  "cartographyProfile": "electron_node" | "micro_frontend" | "device_web" | "unknown",
  "techStack": { "languages": [], "frameworks": [], "notes": "" },
  "architecture": { "summary": "", "entryPoints": [], "modules": [] },
  "conventions": { "fromClaudeMd": [], "fromRules": [] },
  "boundSkills": [ /* 仓内 .claude/skills 元数据 */ ],
  "specAtlas": {
    "entries": [ /* guide/skill/rule/doc_ref；含 DR/DS 若发现 */ ],
    "drDs": [{ "path": "", "kind": "DR|DS|unknown", "moduleHint": null }],
    "bindings": [ /* spec ↔ module/code */ ]
  },
  "capabilities": { "codeGraph": true },
  "defectCodeMatches": [
    {
      "defectId": "", "clusterId": "", "title": "",
      "candidates": [{ "path": "", "symbol": "", "why": "", "source": "codegraph|grep" }],
      "confidence": "high|medium|low"
    }
  ]
}
```

缓存键倾向：`baseSha` + `.claude`/指南哈希 + 注入 skill 集合 + **`defect-batch` 内容哈希**（缺陷集变则匹配段失效；纯架构段可按 sha 复用）。

### 3.5 SDD / 项目约定：框架无关发现

**共识**：

- SDD 形态很多（OpenSpec、Superpowers、Trellis、自研……），**禁止**品牌白名单主路径。  
- 约定与 skills **集中在仓内 `.claude/`**（+ 根目录 `CLAUDE.md` 等）。  
- `.claude` = **发现总线**；具体 SDD 是乘客。  
- **DR/DS**：按路径/命名/文档索引探测并写入 `specAtlas.drDs`，不假设唯一目录约定。

```text
{repo}/CLAUDE.md | AGENTS.md（若存在）
{repo}/.claude/   skills | rules | commands | agents | settings | …
需求/设计：DR、DS 及文档内相对路径引用（二次展开）
```

| 字段 | 含义 |
|---|---|
| `source` | `claude_dir` \| `repo_root` \| `explicit` \| `follow_ref` |
| `kind` | `guide` / `skill` / `rule` / `command` / `agent_def` / `doc_ref` / `dr` / `ds` / `unknown` |
| `frameworkHint` | 可选弱提示，**不得**作控制流分支 |

### 3.6 Skills 注入与形态（相对 Agent-1）

三路来源：仓内 `.claude/skills` ∪ Run 额外注入 ∪ 本包 cartography 内置（通用 SOP，不教具体 SDD 品牌）。

约束：只读工具；`profiles: [cartography]`；挂载 **merge** 不清空仓内 skills。

**与 Agent-1 的差异（待拍）**：Agent-2 含架构理解 + 缺陷匹配，更可能需要**真会话**；CodeGraph + 仓内 skill 是主力。是否也收成「一个 cartography skill + 短会话」、还是独立 Cartographer Agent，探讨中倾向于：

- SOP 用 skill（如 `code-cartography`）声明；  
- 执行上仍是一次（或按形态一次）只读 SDK 会话；  
- **不是**纯 0-LLM 管线（与 Agent-1 不同）。

### 3.7 市场 skill 调研（2026-10-30，选型未定）

检索范围：Cult of Claude、skills.sh、agentskills、GitHub、LobeHub 等。

#### 较适合的候选

| 层 | Skill | 来源 | 备注 |
|---|---|---|---|
| 确定性地图 | **repo-map** | [pm-claude-skills/repo-map](https://github.com/mohitagw15856/pm-claude-skills/blob/main/skills/repo-map/SKILL.md) | 树 + 符号；与 `repo-map.ts` 同构；**CodeGraph 可用时降为辅** |
| 确定性地图 | **codebase-explainer** | [milad-ahmd/agent-skills](https://milad-ahmd.github.io/agent-skills/skills/codebase-explainer/) | import graph → JSON |
| 理解 SOP | **investigating-codebases** | [investigating-codebases](https://github.com/C0ntr0lledCha0s/claude-code-plugin-automations/blob/main/research-agent/skills/investigating-codebases/SKILL.md) | 轻量侦察 |
| 理解 SOP | **codebase-explorer** | [quicksilversurfer/codebase-explorer](https://github.com/quicksilversurfer/codebase-explorer) | archetype + 纵向切片 |
| 理解 SOP | **codebase-deep-research** / **code-investigator** | skills.sh | 证据链导向 |

#### 慎用 / 不建议作主路径

cartographer（默认写目标仓）、Understand-Anything（耦合重）、explore-repo（多 teammate）、默认 Write 进仓的 map skill。

探讨中的默认栈：

```text
读 CLAUDE.md（含 CodeGraph 用法）+ 形态框架（§3.2）
  + .claude / DR·DS 发现
  + defect-batch 逐条匹配（≤~30）
  +（可选）repo-map / import graph 补全
  → code-knowledge.json
```

### 3.8 Agent-2 拍板状态

- [x] `defectCodeMatches` **按条**（非按簇）；批次规模预估 ≤30  
- [x] CodeGraph 在用户仓内；**用法跟 `CLAUDE.md`，不另订发现协议**  
- [x] 三形态：**初步分析框架已写入 §3.2**；细探测/skill 暴露等业务示例仓后再特化  
- [ ] 单条匹配置信度规则  
- [ ] 运行时：独立会话 Agent vs「cartography skill + 单次会话」  
- [ ] 架构段缓存与缺陷匹配段失效策略（≤30 条时可随 batch 全量重算匹配段）  
- [ ] （阻塞特化）各形态业务示例仓 + 测试模块↔子应用/进程对照 

---

## 4. Agent-3：分析与报告

### 4.1 三层分析

1. **定位**（localization）——强制引用 `code-knowledge` + `scopeHint`  
2. **根因**（rootCause）——证据链可核查  
3. **修复方案**（proposedFix + 验证方案设计，不执行）

报告双形态倾向：机器 JSON + 人读 MD；交接字段保留 `ruledOut` / `openQuestions`（见 10-23）。

### 4.2 「可修 / 不可修」语义

探讨张力：

- 用户表述：报告给出可修复与不可修复的详细说明。  
- 10-23 设计：去掉 `fixability` gate，改为 `confidence` + `suggestedAction`，**不丢条、只路由**。

当前记录的折中倾向（未拍板）：

| 对外说法 | 底层字段 |
|---|---|
| 建议改码 | `suggestedAction=code_fix` + confidence |
| 需补证 / 运行时 | `needs_runtime_info` / `needs_design_input` |
| 非代码 / 依赖配置 | `not_code` / `config_or_dependency` |

若产品必须保留「可修/不可修」文案，可将后两类映射为「不可修复（原因码）」，但证据纪律仍走可计算字段，避免模型自由二元裁决。

---

## 5. 与现有代码 / 文档的关系

| 现有 | 关系 |
|---|---|
| `pipeline/normalize` + `aggregate` | Agent-1 规则层可演进基础 |
| `pipeline/repo-map.ts` | Agent-2 确定性骨架过薄；待升级或替换为脚本地图 |
| `pipeline/analyze.ts` | Agent-3 主干；需改为消费 defect-batch + code-knowledge |
| `skills/manifest.ts` `mountSkillsIntoCwd` | Cartographer 需 merge 挂载，避免抹掉仓内 `.claude/skills` |
| 10-23 报告契约 | Agent-3 输出应对齐或显式差分 |
| 10-30 筛选分簇文 | Agent-1 漏斗细则 |

---

## 6. 待拍板清单

| ID | 问题 | 备注 |
|---|---|---|
| Q-A | 缺陷拉取是否进入 Agent-1 | ✅ 纳入；MCP 准/爬虫备；`raw-defects` 解耦 |
| Q-B | 报告结论：可修/不可修 vs confidence+suggestedAction | 见 §4.2（偏 Agent-3） |
| Q-C | Agent-2 市场 skill / CodeGraph | CodeGraph **仓内**；匹配 **按条**（≤~30）；市场 skill 移植清单仍开 |
| Q-D | `code-knowledge` / `defect-batch` / `analysis-report` 最终 schema | 探讨后单开契约文 |
| Q-E | 三 Agent 同进程阶段 vs 分进程/分服务 | Agent-1 已降为 Skill+管线；2/3 待定 |
| Q-F | 是否先写正式规格再实现，还是边定契约边开 PR | 当前明确：**继续探讨，不实现** |

---

## 7. 非目标（本稿）

- 不改 `src/`、不增依赖、不移植 skill 正文  
- 不定最终 zod schema  
- 不更新 `CLAUDE.md` 产品定位（待架构拍板后再改）  

---

## 8. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 初稿：三 Agent 切分、Agent-2 SDD 框架无关 + `.claude` 发现、市场 skill 调研记录；状态=探讨中 |
| 2026-11-01 | Agent-1 分簇改为 L1 测试模块 → L2 标题括注 → L3 AI 意图；补全 Agent-1 端到端流程；同步筛选分簇文 R4/R5 |
| 2026-11-01 | 拉取纳入（MCP 准/爬虫备）且与后续解耦；结论：Agent-1 宜 Skill+规则管线，不必独立长会话 Agent |
| 2026-11-01 | **Agent-1 探讨收口**（用户确认）；遗留仅枚举/MCP 字段契约等实现前细节 |
| 2026-11-01 | Agent-2 补充：三形态、持全部缺陷标题、DR/DS、CodeGraph 主查找、缺陷↔代码匹配 |
| 2026-11-01 | Agent-2：匹配按条（≤~30）；CodeGraph 位于用户仓内 |
| 2026-11-01 | CodeGraph 跟 CLAUDE.md、不另订发现协议；三形态初步通读框架（待样本特化） |
