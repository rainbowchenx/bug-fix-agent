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
| 运行时 | **推荐：LangGraph 编排 + Claude Agent SDK 会话**；Skill / MCP 为附着能力（§6 评估） |

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

相对 Agent-1：`defect-batch-prepare` = Skill + 代码管线；Agent-2 = **图编排的 Cartographer Agent（SDK）** + Skill/MCP 附着。

### 6.4 风险与约束

- 匹配节点按条或小批，避免单会话塞满 30 条全文。  
- 架构节点与匹配节点产物分离，便于 `baseSha` 缓存架构段。  
- 只读：`disallow Edit/Write`（或写仅限 run 目录 artifact）。  
- `mountSkillsIntoCwd` 对目标仓 **merge**。  

---

## 7. Skills 注入（附着层）

仓内 `.claude/skills` ∪ Run 额外注入 ∪ 本包 cartography 内置。  
只读；`profiles: [cartography]`；挂载 **merge**。  

市场候选（选型未定）：repo-map、codebase-explainer、investigating-codebases、codebase-explorer 等；CodeGraph 可用时脚本 map 为辅。

---

## 8. 拍板状态

- [x] 匹配按条（≤~30）  
- [x] CodeGraph 跟 `CLAUDE.md`，不另订发现协议  
- [x] 三形态初步框架（§2）；细项待示例仓特化  
- [x] SDD = 封闭已知集 + 通读识别（名单待样本冻结）  
- [x] 运行时推荐：**LangGraph + Claude Agent SDK**；Skill/MCP 附着（§6）  
- [ ] SDD `frameworkId` 封闭名单终版  
- [ ] 单条匹配置信度规则  
- [ ] Cartographer 子图节点切分终版  
- [ ] 缓存失效策略  
- [ ] （阻塞特化）各形态业务示例仓  

与现有代码：已有 `src/graph/*` + `sdk-runner.ts`；Cartographer 宜新子图，复用挂载/MCP 合并模式。`repo-map.ts` 过薄；`mountSkillsIntoCwd` 需 merge。

---

## 9. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出 |
| 2026-11-01 | 三形态 / CodeGraph / 按条匹配等 |
| 2026-11-01 | SDD 改为封闭已知集；运行时评估结论为 LangGraph + Claude Agent SDK |
