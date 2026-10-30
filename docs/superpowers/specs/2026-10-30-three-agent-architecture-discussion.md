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
| Agent-1 | 缺陷拉取（可选）→ 筛选 → **多层分簇** → 结构化批次 |
| Agent-2 | 对用户指定目录通读 → 架构/模块知识包 → **可跨 run 缓存共享** |
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
| 蒸馏描述模板、清洗、模块取值 | 通读业务源码 |
| 规则硬分流（CVE / 端侧 / 偶现 / 信息过薄等） | 根因与改码 |
| 多层分簇 + 优先级 | 绑定具体缺陷平台写操作（若拉取外置则连读也不做） |

### 2.2 分簇层次（探讨稿）

- **L1** 模块 / 仓桶（对齐 `repoMapping` 或筛选文中的测试模块键）  
- **L2** 症状相似度（标题 + 实际结果归一化）  
- **L3** 疑似同根因（可选；或等 Agent-3 回写合并）

详细漏斗（R0–R6、`strict` 主池等）以 `2026-10-30-defect-screen-cluster-design.md` 为准；与本层冲突时优先更新该文或在本文「待拍板」注明。

### 2.3 待拍板

- [ ] 缺陷平台**拉取**是否纳入 Agent-1，还是继续由外部工作流保证 `defects[]` 已落地  
- [ ] 对外报告用「可修/不可修」还是 `confidence` + `suggestedAction`（见 §4）

---

## 3. Agent-2：代码通读（Code Cartographer）

### 3.1 职责

对用户指定目录（git 仓）做只读理解，产出可共享的 `code-knowledge`，供 Agent-3 与后续 run 复用。

建议产物形态（探讨）：

```jsonc
{
  "baseSha": "…",
  "modules": [{ "name", "dirs", "entryPoints", "dependsOn", "specRefs" }],
  "routes": [],
  "i18nIndex": {},
  "hotPaths": [],
  "specAtlas": {
    "entries": [ /* 见 §3.2 */ ],
    "bindings": [ /* spec ↔ module/code */ ]
  }
}
```

缓存键倾向：`baseSha` + 指南/`.claude` 内容哈希 + 注入 skill 集合。

### 3.2 SDD / 项目约定：框架无关发现

**共识（已强调多次）**：

- SDD 形态很多（OpenSpec、Superpowers、Trellis、自研……），**禁止**做成品牌白名单主路径。  
- 一般约定与 skills **集中在用户指定仓的 `.claude/`**（另加根目录 `CLAUDE.md` 等 Claude 生态惯例文件）。  
- `.claude` 是**发现总线**；具体 SDD 是总线上的乘客。

探测姿态：

```text
{repo}/CLAUDE.md | AGENTS.md（若存在）
{repo}/.claude/
  skills/**/SKILL.md
  rules/**
  commands/** | agents/** | settings*.json
  …任意自定义结构 → 一律收录，kind=unknown 亦可
```

索引字段倾向：

| 字段 | 含义 |
|---|---|
| `source` | `claude_dir` \| `repo_root` \| `explicit` \| `follow_ref` |
| `kind` | `guide` / `skill` / `rule` / `command` / `agent_def` / `doc_ref` / `unknown` |
| `frameworkHint` | **可选弱提示**，允许 `null`；**不得**作为控制流分支 |

从清单内的相对路径再展开到真实 spec/需求（二次发现）。`business.specPaths` / 显式路径为最高优先覆盖。

### 3.3 Skills 注入

三路来源（同名策略待定；倾向用户/仓覆盖内置）：

1. **仓内** `{repo}/.claude/skills`  
2. **Run 额外注入** `extras.skillsDir` / skill 列表  
3. **本包 cartography 内置**——只保留通用 SOP（如何遍历 `.claude`、追文档引用、写 modules/bindings），**不教某个 SDD 产品**

约束：

- 会话只读：`Read` / `Glob` / `Grep` / `Skill`；无 Edit。  
- `profiles: [cartography]`，与修复向 skill 隔离。  
- 挂载时应对仓内 `.claude/skills` **merge 而非清空**（现有 `mountSkillsIntoCwd` 的 `rm` 整树行为在 Cartographer 路径需改）。

### 3.4 市场 skill 调研（2026-10-30，选型未定）

检索范围：Cult of Claude、skills.sh、agentskills、GitHub、LobeHub 等。

#### 较适合 Agent-2 的候选

| 层 | Skill | 来源 | 备注 |
|---|---|---|---|
| 确定性地图 | **repo-map** | [pm-claude-skills/repo-map](https://github.com/mohitagw15856/pm-claude-skills/blob/main/skills/repo-map/SKILL.md) | 树 + 行数 + 顶层符号；先 map 再开文件；与现有 `repo-map.ts` 同构 |
| 确定性地图 | **codebase-explainer** | [milad-ahmd/agent-skills](https://milad-ahmd.github.io/agent-skills/skills/codebase-explainer/) | 真实 import graph → JSON；可喂 `dependsOn` |
| 理解 SOP | **investigating-codebases** | [investigating-codebases/SKILL.md](https://github.com/C0ntr0lledCha0s/claude-code-plugin-automations/blob/main/research-agent/skills/investigating-codebases/SKILL.md) | 轻量侦察流程；易裁成只读 |
| 理解 SOP | **codebase-explorer** | [quicksilversurfer/codebase-explorer](https://github.com/quicksilversurfer/codebase-explorer) | archetype + 纵向切片 + smell |
| 理解 SOP | **codebase-deep-research** | [skills.sh](https://www.skills.sh/bleedingdev/training-skills/codebase-deep-research) | 多角度 + 主张需文件证据 |
| 理解 SOP | **code-investigator** | [skills.sh](https://www.skills.sh/atman-33/skills/code-investigator) | 证据链 / Mermaid / confirmed vs unknown |

#### 可选增强（重，慎用）

| Skill / 产品 | 来源 | 风险 |
|---|---|---|
| cartographer | [kingbootoshi/cartographer](https://github.com/kingbootoshi/cartographer) | 默认写目标仓 `docs/CODEBASE_MAP.md` / 改 `CLAUDE.md`；依赖子 agent |
| Understand-Anything | [Lum1104/Understand-Anything](https://github.com/Lum1104/Understand-Anything) | 知识图谱能力强；与「落盘 JSON 交接」耦合重 |
| mapping-codebases | [oaustegard/claude-skills](https://github.com/oaustegard/claude-skills/tree/main/mapping-codebases) | AST map 好，但易在仓内撒 `_MAP.md` |
| Archify / AOCI | Cult of Claude 等 | 可视化 IR / 持久索引；不适合 MVP 主干 |

#### 不太建议作主 skill

- **explore-repo**（多 teammate / `TeamCreate`）——与本包 SDK 会话模型不合  
- **understand-codebase-architecture**（交互 HTML）——偏人读，非 Agent-3 机器契约  
- 任何默认 **Write 进目标仓** 的 map skill——须改输出到 run 目录后方可考虑  

#### 探讨中的默认栈（未拍板）

```text
确定性: repo-map 脚本 + codebase-explainer import graph
     ↓
模型 SOP: investigating-codebases / codebase-explorer（精简移植）
     + 仓内 .claude skills
     ↓
落盘: code-knowledge.json
```

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
| Q-A | 缺陷拉取是否进入 Agent-1 | 凭据仍不进模型上下文 |
| Q-B | 报告结论：可修/不可修 vs confidence+suggestedAction | 见 §4.2 |
| Q-C | Agent-2 默认采用哪些市场 skill（移植清单） | 见 §3.4 |
| Q-D | `code-knowledge` / `defect-batch` / `analysis-report` 最终 schema | 探讨后单开契约文 |
| Q-E | 三 Agent 同进程阶段 vs 分进程/分服务 | 影响部署与缓存 |
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
