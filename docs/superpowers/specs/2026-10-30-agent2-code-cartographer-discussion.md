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
| 运行时 | 相对 Agent-1 更像真会话；倾向 cartography **Skill + 只读会话**（待拍） |

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

## 5. SDD / `.claude`（框架无关）

- 不以 OpenSpec / Superpowers / Trellis 等品牌为准。  
- `.claude` = 发现总线；`CLAUDE.md` / `AGENTS.md` 一并读。  
- DR/DS 探测写入 `specAtlas.drDs`。  

| 字段 | 含义 |
|---|---|
| `source` | `claude_dir` \| `repo_root` \| `explicit` \| `follow_ref` |
| `kind` | `guide` / `skill` / `rule` / `command` / `agent_def` / `doc_ref` / `dr` / `ds` / `unknown` |
| `frameworkHint` | 可选弱提示，**不作**控制流 |

---

## 6. Skills 注入

仓内 `.claude/skills` ∪ Run 额外注入 ∪ 本包 cartography 内置（通用 SOP）。  
只读；`profiles: [cartography]`；挂载 **merge**。  

市场候选（选型未定）：repo-map、codebase-explainer、investigating-codebases、codebase-explorer、deep-research / code-investigator。慎用默认写目标仓的 cartographer 类。

默认栈：

```text
读 CLAUDE.md（含 CodeGraph）+ 形态框架
  + .claude / DR·DS
  + defect-batch 逐条匹配
  +（可选）repo-map / import graph
  → code-knowledge.json
```

---

## 7. 拍板状态

- [x] 匹配按条（≤~30）  
- [x] CodeGraph 跟 `CLAUDE.md`，不另订发现协议  
- [x] 三形态初步框架（§2）；细项待示例仓特化  
- [ ] 单条匹配置信度规则  
- [ ] 运行时：独立会话 vs cartography skill + 单次会话  
- [ ] 缓存失效策略  
- [ ] （阻塞特化）各形态业务示例仓  

与现有代码：`repo-map.ts` 过薄；`mountSkillsIntoCwd` 需 merge。

---

## 8. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-10-30 | 自三 Agent 合稿拆出 |
| 2026-11-01 | 三形态 / CodeGraph / 按条匹配等（合稿内已记） |
