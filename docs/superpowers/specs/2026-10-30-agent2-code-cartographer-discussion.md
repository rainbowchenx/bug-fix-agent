# Agent-2 探讨：代码通读（Code Cartographer）

> 日期：2026-10-30（2026-11-01 修订）  
> 状态：**探讨中**（非正式规格）  
> 索引：[三 Agent 架构索引](2026-10-30-three-agent-architecture-discussion.md)  
> 上游：[Agent-1](2026-10-30-agent1-defect-batch-discussion.md) · 下游：[Agent-3](2026-10-30-agent3-defect-analyst-discussion.md)

---

## 0. 结论（当前）

| 项 | 倾向 |
|---|---|
| 输入 | `workDir` + 上一轮 **`defect-batch`（全部缺陷，至少标题）** |
| 形态 | `electron_node` / `micro_frontend` / `device_web`（§2 初步框架，待样本特化） |
| 查找 | 仓内 **CodeGraph**；用法跟用户仓 **`CLAUDE.md`**，不另订发现协议 |
| 匹配 | **按缺陷条目**；批次预估 ≤30 |
| 产出 | `code-knowledge`（含架构、skill/SDD/DR·DS、`defectCodeMatches`） |
| SDD | **封闭已知集合**（几种固定框架）；通读仓内即可识别；不写死单一品牌，也不做成开放臆造 |
| 运行时 | LangGraph 编排 + Claude Agent SDK；Skill / MCP 附着（§6） |
| 通用 Skill | **§7.1 已确认**：investigating-codebases + codebase-explorer（裁剪）+ 可选脚本 |
| 业务 Skill | **允许注入**（`profiles: cartography`）；指导形态/子应用/设备桥等业务通读要点 |
| 对外耦合 | **仅**消费已校验的 `defect-batch`，产出已校验的 `code-knowledge`；不与 Agent-1/3 内部实现耦合 |
| I/O 校验 | 输入前校验 batch；输出后校验 knowledge；失败不进入 Agent-3 |

---

## 1. 职责与输入

对用户指定目录只读理解，产出可共享的 `code-knowledge`。

| 输入 | 说明 |
|---|---|
| `workDir` / 仓路径 | 用户指定代码目录 |
| **`defect-batch`** | 已分类的全部缺陷（至少标题；建议带 clusterId / testModule / titleTag / intent） |
| 可选 extras | 额外 cartography skills、显式 `specPaths` |

要完成：

1. 技术架构 / 技术栈（§2）  
2. 已绑定 skill、已用 SDD、开发约定（`.claude` 发现总线）  
3. 需求文档 **DR/DS** 位置（如有）  
4. **缺陷 ↔ 代码**按条匹配（CodeGraph 优先）  

---

## 2. 三种代码形态（初步框架，待样本特化）

> 与旧 install/verify Stack Profile 正交；只服务理解与匹配。

共用骨架：

```text
1. 读 CLAUDE.md / .claude → 约定、skills、SDD、CodeGraph 用法
2. 判 primaryProfile（可带 secondaryHints）
3. 按形态清单填 architecture / techStack / modules
4. 收 DR/DS 与 spec 绑定
5. 对 ≤~30 条缺陷逐条匹配 → defectCodeMatches
```

### 粗探测信号（初版）

| Profile | 正向信号（示例） | 注意 |
|---|---|---|
| `electron_node` | `electron`；main/preload；electron-builder / electron-vite | 纯 Node 后端可作子型 |
| `micro_frontend` | `single-spa`；根注册表；多子应用入口 | 与纯 monorepo 库仓区分 |
| `device_web` | 设备桥 / 嵌入壳 / 弱桌面路由 | 形态看嵌入约束，不看 UI 框架名 |

### A. `electron_node`

| 分析维 | 问题 | 落盘提示 |
|---|---|---|
| 进程边界 | 主/渲染/preload 入口？ | `modules[].role` |
| IPC | channel / invoke？ | `architecture.ipcSurface[]` |
| 窗口与路由 | BrowserWindow；渲染路由 | `entryPoints` |
| 打包与环境 | 开发/生产、额外 Node 服务 | `techStack.notes` |
| 匹配偏置 | 闪退/托盘/IPC→主进程；UI 文案→渲染 | `candidates[].why` |

### B. `micro_frontend`（single-spa）

| 分析维 | 问题 | 落盘提示 |
|---|---|---|
| 基座 | 根配置 / `registerApplication`？ | `architecture.shell` |
| 子应用 | 入口、路由前缀、部署名 | `modules[]` 一应用一模块 |
| 共享层 | 公共依赖 / 权限 | `modules[].shared` |
| 跨应用 | props / 事件 / 全局状态 | `architecture.crossApp` |
| 匹配偏置 | 测试模块/括注→子应用，再 CodeGraph | `moduleHint` |

### C. `device_web`

| 分析维 | 问题 | 落盘提示 |
|---|---|---|
| 嵌入宿主 | 设备壳如何加载？ | `architecture.embedHost` |
| 设备桥 | JSBridge / 原生 API | `architecture.deviceBridge[]` |
| 运行约束 | 离线、分辨率、内核、权限 | `techStack.constraints` |
| 页面结构 | 预览/回放/设置等 | `modules[]` 按功能面 |
| 匹配偏置 | 云台/码流等→模块+桥层 | 区分纯 H5 vs 桥失败 |

### 匹配共用规则（已定）

- **按条**；预估 ≤30  
- 查询词：标题 + titleTag + testModule +（可选）intent  
- 形态只影响优先搜哪类边界，不改粒度  

---

## 3. CodeGraph

- 在**用户仓库**内。  
- **用法以该仓 `CLAUDE.md`（及其指向）为准**；本产品**不另订**发现协议。  
- 通读必读 `CLAUDE.md`；失败则降级 Glob/Grep/Read，记 `capabilities.codeGraph=false`。  

---

## 4. 产物草案

```jsonc
{
  "baseSha": "…",
  "cartographyProfile": "electron_node" | "micro_frontend" | "device_web" | "unknown",
  "techStack": { "languages": [], "frameworks": [], "notes": "" },
  "architecture": { "summary": "", "entryPoints": [], "modules": [] },
  "conventions": { "fromClaudeMd": [], "fromRules": [] },
  "boundSkills": [],
  "specAtlas": {
    "entries": [],
    "drDs": [{ "path": "", "kind": "DR|DS|unknown", "moduleHint": null }],
    "bindings": []
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

缓存：`baseSha` + `.claude`/指南哈希 + skill 集合 + **`defect-batch` 哈希**（匹配段随缺陷集失效；架构段可按 sha 复用）。

---

## 5. SDD / `.claude`（封闭已知集 + 通读识别）

修正此前「完全不定品牌」的表述：

| 原则 | 说明 |
|---|---|
| **不指定唯一** | 不以某一 SDD 为产品绑定 |
| **集合固定** | 业务侧会出现的是**有限几种**（如 Superpowers / OpenSpec / Trellis / 自研变体等——**名单随样本仓冻结**） |
| **通读识别** | 读 `CLAUDE.md`、`.claude/`、目录指纹即可判定命中哪一种；写入 `specAtlas.frameworkId` |
| **未知** | 不在名单内 → `frameworkId=unknown` + 仍收录 paths；**禁止**模型编造新品牌名当权威 |

`.claude` 仍是发现总线；DR/DS → `specAtlas.drDs`。

| 字段 | 含义 |
|---|---|
| `frameworkId` | 封闭枚举之一或 `unknown`（名单待样本冻结） |
| `source` | `claude_dir` \| `repo_root` \| `explicit` \| `follow_ref` |
| `kind` | `guide` / `skill` / `rule` / `command` / `agent_def` / `doc_ref` / `dr` / `ds` / `unknown` |

---

## 6. 运行时评估：Skill+MCP vs Agent（结论）

固定约束：**编排 = LangGraph**；**会话内核 = `@anthropic-ai/claude-agent-sdk`（Claude Code SDK）**。  
问题不是二选一「只要 Skill」或「只要 Agent」，而是 **Agent-2 节点里要不要上 SDK 会话**，以及 Skill/MCP 放哪一层。

### 6.1 对照

| 方案 | 含义 | 对 Agent-2 |
|---|---|---|
| **A. 仅 Skill + MCP** | 宿主按 skill SOP 调 MCP；无（或极薄）自主会话 | 难扛「架构通读 + ≤30 条匹配」的探索环；阶段状态、重试、产物门禁弱 |
| **B. 单次超长 SDK 会话** | 一个 query 做完全部 | 上下文易胀；架构与逐条匹配互相污染；不利缓存架构段 |
| **C. LangGraph + SDK 会话（推荐）** | 图管阶段与 artifact；节点内 SDK 只读会话；Skill 注入 SOP；MCP/仓内工具按 `CLAUDE.md` | 与仓库已有双引擎定位一致；可拆「地图 / 匹配」 |

### 6.2 为何 Agent-2 不宜学 Agent-1「纯 Skill+管线」

Agent-1 主路径 **0 LLM、可复算规则** → Skill 只声明 SOP + 代码跑漏斗。  
Agent-2 主路径是 **探索 + 推理 + 工具环**（读约定、判形态、认 SDD、CodeGraph 查询、逐条写匹配）→ 需要 **SDK Agent 会话**；Skill/MCP 是增强，替不了会话。

### 6.3 推荐形状

```text
LangGraph（Cartographer 子图）
  ├─ node: bootstrap     读 CLAUDE.md / .claude；探测 profile + frameworkId（可轻量/规则+短会话）
  ├─ node: map_arch      SDK 只读会话 → architecture / techStack / boundSkills / drDs
  ├─ node: match_defect  按条（≤30）SDK 或短会话 + CodeGraph（用法跟 CLAUDE.md）
  └─ node: synthesize    校验合并 → code-knowledge.json（zod）
         ▲
    Skills（cartography / 形态 SOP）  MCP 或仓内 CodeGraph 工具
```

| 层 | 职责 |
|---|---|
| **LangGraph** | 阶段边、checkpoint、失败重试、与 run 目录 artifact 对齐 |
| **Claude Agent SDK** | 节点内只读工具环（Read/Glob/Grep/Skill + 仓内声明的 CodeGraph） |
| **Skills** | 通读 SOP、形态关注点、匹配写法；**不**单独当编排器 |
| **MCP** | 若 `CLAUDE.md`/仓配置把 CodeGraph 等暴露为 MCP 则挂上；否则按仓内 CLI——**不强制本产品自建 CodeGraph MCP** |

相对 Agent-1：`defect-batch-prepare` = Skill + 代码管线；Agent-2 = **本单元内**图编排的 Cartographer（SDK）+ Skill/MCP 附着。  
对外仍是工作流上的**独立一步**：只认校验过的 `defect-batch` / `code-knowledge`，不与 Agent-1/3 实现合并。

### 6.4 风险与约束

- 匹配节点按条或小批，避免单会话塞满 30 条全文。  
- 架构节点与匹配节点产物分离，便于 `baseSha` 缓存架构段。  
- 只读：`disallow Edit/Write`（或写仅限 run 目录 artifact）。  
- `mountSkillsIntoCwd` 对目标仓 **merge**。  

---

## 7. Skills 注入（附着层 + 业务特性）

**三端共识**：用户可注入业务特性 Skill（见[索引](2026-10-30-three-agent-architecture-discussion.md)）。本段：

| 来源 | 用途 |
|---|---|
| 仓内 `.claude/skills` | 项目自带通读/SDD/CodeGraph 习惯 |
| Run / `.bugfix/skills` **业务注入** | 线别：子应用↔测试模块对照、设备桥词表、微前端注册表路径等 |
| 本包 cartography 内置 | 通用 SOP；可被业务覆盖 |

只读；`profiles: [cartography]`；挂载 **merge**。业务 skill **指导**匹配偏置与目录习惯，**不**改 `code-knowledge` zod 门禁。

### 7.1 通用通读 Skill 选型（**已确认**，按此落地）

> 2026-11-01 确认：先按本表内置/裁剪移植；业务 skill 仍可叠加注入。

前提：仓内 **CodeGraph**（跟 `CLAUDE.md`）已是主查找；通用 skill 只补「怎么通读 / 怎么写知识包」，不要再上重型全仓写文档类 skill。

| 优先级 | Skill | 角色 | 理由 |
|---|---|---|---|
| **P0 主 SOP** | **investigating-codebases** | 通用侦察流程（结构→入口→依赖→文档） | 轻量、工具面 Read/Grep/Glob，与 CodeGraph 不抢主检索；易裁成只读 cartography |
| **P0 架构补强** | **codebase-explorer**（精简移植） | 形态/archetype + 纵向切片 | 与三形态（electron / 微前端 / 设备 Web）同构；用于 `map_arch` 节点，勿默认写目标仓 |
| **P1 脚本辅** | **codebase-explainer** 的 `code_map` 脚本 | import graph → JSON | 确定性补 `dependsOn`/hubs；CodeGraph 降级或要图数据时用 |
| **P1 导航辅** | **repo-map** | 树 + 顶层符号 +「先 map 再开文件」 | CodeGraph 不可用时的廉价索引；对齐现有 `repo-map.ts` 升级方向 |
| **P2 可选** | **code-investigator** / **codebase-deep-research** | 证据链、file:line | 匹配节点若要加严举证可摘条款，不必整包 |

**不推荐作 Agent-2 主 skill**：`cartographer`（默认写 `CODEBASE_MAP.md`/改仓内 CLAUDE）、`explore-repo`（多 teammate）、交互 HTML 类 architecture map。

建议内置组合（实现时精简移植，非原样整仓拷贝）：

```text
code-cartography/SKILL.md          ← 本段总 SOP（读 CLAUDE.md → 形态 → SDD → 架构 → 按条匹配）
  + investigating-codebases（裁剪）
  + codebase-explorer 形态/切片条款（裁剪）
  +（可选脚本）code_map / repo_map
  + 用户业务 skill（子应用对照、设备桥等）
```

Agent-2 **段内**仍可拆节点（架构 vs 匹配），但对外仍是一个工作流步骤；**不**把会话上下文传给 Agent-3。

---

## 8. 拍板状态

### 8.1 已确认

- [x] 匹配按条（≤~30）  
- [x] CodeGraph 跟 `CLAUDE.md`，不另订发现协议  
- [x] 三形态**初步框架**（§2）；细探测待示例仓特化  
- [x] SDD = 封闭已知集 + 通读识别（**名单**仍待冻）  
- [x] 运行时：段内 **LangGraph + Claude Agent SDK**；Skill/MCP 附着  
- [x] 业务 Skill 可注入（cartography）；通用 skill 按 §7.1  
- [x] 工作流独立单元；I/O 契约 + 进出脚本校验；不共享跨 Agent 会话  

### 8.2 仍待确认（审阅清单）

按「是否挡住 Agent-2 探讨收口 / 实现」分组。

#### A. 建议本轮就拍（产品语义，可不靠样本仓）

| ID | 问题 | 现状缺口 | 可选默认（若不反对可按此） |
|---|---|---|---|
| **A1** | `defect-batch` 入参**必填字段** | 现写「至少标题；建议带 clusterId/…」 | 必填：`defectId,title`；强建议：`clusterId,testModule,titleTag,intent`（缺则匹配置信度封顶 medium） |
| **A2** | 实际条数 **>30** 怎么办 | 只写了预估 ≤30 | **硬拒**整批 Agent-2（校验失败），或截断 Top30 并告警——需选一 |
| **A3** | 单条 `candidates` 上限与空匹配 | 草案无上限、空数组未定义 | 最多 **3** 条候选；允许空数组且 `confidence=low` |
| **A4** | 匹配置信度规则 | 仅有枚举 | 有 CodeGraph 命中+路径存在→可 high；仅 grep→最多 medium；无候选→low；`codeGraph=false` 时全体上限 medium |
| **A5** | 匹配失败 / 中途失败是否仍出 knowledge | 未写 | **仍产出**架构段 + 已完成匹配；`synthesize` 带 `partial=true`；工作流是否放行 Agent-3 由父图策略定（默认：校验过 schema 即放行） |
| **A6** | 段内写权限 | 「只读」vs「可写 run 目录」 | SDK **禁止改目标仓**；允许写 `{runDir}/…` artifact |
| **A7** | `match_defect` 串行还是有限并行 | 未写 | 默认**串行**（简）；或并发 3（吞吐）——需选一 |
| **A8** | P2 skill（investigator/deep-research）默认是否装 | 标可选 | **默认不装**；实现期按需再加 |
| **A9** | 子图四节点是否定稿 | §6.3 为推荐 | 确认采用 `bootstrap → map_arch → match_defect → synthesize` |

#### B. 可延后到样本仓 / 契约专文（不挡「主路径收口」叙事）

| ID | 问题 | 说明 |
|---|---|---|
| **B1** | SDD `frameworkId` 封闭名单 | 等各业务仓看齐后冻结 |
| **B2** | 三形态探测指纹与业务对照表 | 等 electron / spa / device 示例仓 |
| **B3** | `code-knowledge` schemaVersion 终版字段表 | 跨段 Q-D；与 Agent-1/3 一起开契约文 |
| **B4** | 缓存键与失效精策略 | 草案已有方向；实现前可再钉 TTL/目录布局 |
| **B5** | `specPaths` 是否常驻请求字段 | 现为可选 extras |
| **B6** | 多仓 / monorepo 多 `workDir` | 现假设单目录；双仓以后再开 |
| **B7** | `code-cartography` 总 SOP 正文 | 实现时按 §7.1 新写，非现成第三方包 |

与现有代码：已有 `src/graph/*` + `sdk-runner.ts`；Cartographer 宜**独立子图/单元**，复用挂载/MCP 合并；`mountSkillsIntoCwd` 需 merge；`repo-map.ts` 过薄。

### 8.3 继续审阅：跨文档一致性与草案缺口（C 组）

对照 [Agent-1](2026-10-30-agent1-defect-batch-discussion.md)、[筛选分簇](2026-10-30-defect-screen-cluster-design.md)、[索引](2026-10-30-three-agent-architecture-discussion.md) 后的新发现——**比 A 组更影响契约**，建议优先拍。

| ID | 问题 | 矛盾 / 缺口 | 建议默认 |
|---|---|---|---|
| **C1** | Agent-2 匹配**哪些池**的缺陷？ | 本文写「全部缺陷」；Agent-1 产出含 strict **主队列** + 旁路（hard_reject / needs_info / locatable_only / 安全） | **默认只匹配 `strict` 主队列**；旁路不进 CodeGraph（省 token）。若要对 locatable_only 做弱匹配，需显式开关 |
| **C2** | `defect-batch` 顶层形状 | Agent-1 **未定义** JSON（扁票据 vs 簇数组）；Agent-2 按条匹配 | 约定：`{ schemaVersion, productLine, clusters[], tickets[] }`；`tickets[]` 为匹配真源；`clusters[]` 供上下文 |
| **C3** | 字段名与簇 ID | 筛选文簇 ID=`{line}::{testModule}::{titleTag}::{intent}`；Agent-2 用 clusterId/titleTag | **对齐**筛选文；Agent-2 查询词用 ticket 上的 `testModule`/`titleTag`/`intent`/`title` |
| **C4** | 「至少标题」过软 | Agent-1 对 strict 已产出模块/括注/意图 | 消费 Agent-1 时：**strict ticket 应带齐** `defectId,title,clusterId,testModule,titleTag,intent`；缺字段 → 输入校验 warn + A1 置信度封顶（不是静默「只有标题」） |
| **C5** | `code-knowledge` 草案缺字段 | §5 有 `frameworkId`，§4 JSON 未挂；无 `schemaVersion`/`partial`/`secondaryHints`/`productLine`/`workDir` | 补：`schemaVersion, productLine, workDir, baseSha, partial?, secondaryHints?, specAtlas.frameworkId` |
| **C6** | `partial=true` vs 索引「校验失败硬停」 | A5 允许部分产出；索引写 validate 失败不得下游 | **区分**：schema 合法的 partial 算通过校验；缺必填/类型错误才硬停。父图可读 `partial` 决定是否仍跑 Agent-3 |
| **C7** | `baseSha` / git 前提 | 未写谁解析、非 git 仓怎么办 | Agent-2 bootstrap：`git rev-parse HEAD`；非 git → 输入校验失败（与「指定代码仓」一致） |
| **C8** | 蒸馏正文是否进 Agent-2 | 匹配查询现为标题+tag+module+intent；Agent-1 有实际/期望/步骤 | **默认不灌全文**（防爆）；可选 `includeDigest=false`；需要时只带短 `observed/expected` 摘要字段 |
| **C9** | 与 Agent-3 的最小交接 | 只写了 defectCodeMatches | 明确 Agent-3 **至少**依赖：`defectCodeMatches` + `cartographyProfile` + `modules` + `specAtlas.drDs`；其余可降级缺失 |

**审阅结论（本轮）**：

1. 主路径叙事成立，但 **C1/C2/C5/C6** 不拍清，实现时 I/O 脚本无法写死。  
2. A 组是行为策略；C 组是**契约对齐**——收口 Agent-2 前建议先定 C，再批量接受 A 默认。  
3. B 组（样本仓/SDD 名单）仍可不挡「探讨收口」，但挡「开写 zod」。

---

## 9. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出 |
| 2026-11-01 | 三形态 / CodeGraph / 按条匹配等 |
| 2026-11-01 | SDD 改为封闭已知集；运行时评估结论为 LangGraph + Claude Agent SDK |
| 2026-11-01 | 明确业务特性 Skill 可注入 |
| 2026-11-01 | 松耦合工作流；batch/knowledge 进出校验 |
| 2026-11-01 | 否决跨 Agent 共享上下文；通用通读 skill 选型建议 §7.1 |
| 2026-11-01 | **§7.1 通用 skill 清单确认按此落地** |
| 2026-11-01 | 完整审阅：§8.2 拆成 A 本轮可拍 / B 可延后 |
| 2026-11-01 | **继续审阅**：§8.3 跨文档一致性 C1–C9 |
