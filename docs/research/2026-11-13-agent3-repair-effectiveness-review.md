# Agent-3 修复效果评估与改进建议

日期：2026-11-13。性质：代码审阅与开源调研，供设计讨论；不是已批准的实施规格。未修改产品代码、未调用真实模型、未安装依赖。没有实仓修复成功率数据，因此下面的收益排序是工程判断，不是已测得的提升百分比。

## 1. 结论

当前 Agent-3 已具备较合理的分析入口，但尚未形成修复反馈闭环。最值得投入的是：

1. 先修复根因门禁、workspace 与补丁完整性问题，建立可信的修复评测。
2. 将 Agent-1/2 的产物变成可追溯、按票裁剪的上下文；把分析的证据交给改码会话。
3. 增加按环境能力启用的复现、静态检查、回归和失败回修；无运行环境时继续允许交付未验证 patch。
4. 在以上基础上，再用独立审查、困难票多候选和模型/预算分配提升上限。

不建议先增加 Agent 数量、把 max_turns 普遍调大、整仓替换 SDK 或恢复已退役的 SWE-bench 适配器。也不建议把“没有测试环境”直接当作“不能生成补丁”。

## 2. 当前架构与已有优势

实际执行路径：

```text
Agent-1 defect-batch + Agent-2 code-knowledge
  → run_analyst 循环匹配池票
  → route_ticket 确定性提示
      needs_info → 完整阻断报告
      其余 → 独立只读 analyze SDK（Read/Glob/Grep + CodeGraph）
  → 合并并清洗分析结果
  → apply_fix 且 _actionable_for_fix
      → worktree → 新 fix SDK（Read/Glob/Grep/Edit/Write）
      → git diff → patch_ready / plan_only
  → 单票 schema 校验 → 汇总报告
```

值得保留：

- Agent-2 候选只作软起点；启发式命中降权，空候选仍能进入 Agent-3 自搜。
- Agent-1 在图外，产品边界清楚；仅通过共享契约交换产物。
- 默认只读分析；显式开启才改码，分析与编辑权限分离。
- 非代码、缺信息、缺设计、环境依赖等阻断可以有完整正文。
- SDK 失败不再把路由占位结果包装成成功分析；有预算触顶抢救逻辑。
- 有架构图、规格索引、仓型 playbook、overlay skill、CodeGraph 支持。

入口：`platform/bugfix_platform/agents/analyst/run.py:44`；路由：`agents/analyst/route.py:60`；分析：`sdk/analyze.py:125`；改码：`sdk/fix.py:123`。

### 历史设计必须区分

`docs/superpowers/specs/2026-10-30-agent3-defect-analyst-discussion.md:84,104,218` 已明确放宽早期 GREEN 硬门禁；11-11 规格进一步确定默认报告、改码受开关控制。设备 Web/Electron 经常没有实机、后端、完整依赖，因此不应把执行测试设为所有票产出 patch 的前提。

本报告建议提高“能执行时的反馈质量”和“不能执行时的证据质量”，保留未验证补丁交付，不把旧调研中的全量环境/MR要求原样恢复。`openMr` 当前仍只是报告标志，本文不把真实远端交付当现有能力。

## 3. 当前限制：按影响排序

### 3.1 根因门禁会把占位计划当成可修方案

`route.py:147` 默认根因：

```text
Localization soft-start available; root cause pending analyze session
```

`run.py:242-251` 仅排除以 pending 开头的摘要或摘要中出现 analyze session skipped 的情况；heuristic 只把 skipped 写入 openQuestions，analyze_limit 耗尽也保留路由结果。结果：没有真实分析也可能进入 fix。

本次用 AST 提取现有纯函数执行，上述占位对象 `_actionable_for_fix(...)` 返回 True。此验证没有调用 SDK。

建议不再通过自然语言字符串识别“已证明根因”。改为明确状态与证据：analysisStatus、evidenceRefs、rootCauseStatus、validatedPlan；未执行分析、失败、触顶残片不能自动取得可行动资格。静态证据足够时仍可允许未运行测试的修复。

### 3.2 改码会话没有反馈闭环

`sdk/fix.py:17-18` 不提供执行工具，`:206` 明令不运行测试；`:177-198` 非空 diff 即 patch_ready。没有基线、复现、编译/类型检查、回归失败回灌。

这是当前选择的最小 patch 产出语义，不能据此认定 patch_ready 是“已修好”。但如果目标转为提高真实修复效果，执行反馈是主要增量能力。建议保留 patch_ready 产物语义，并用独立验证状态表示证据强度。

### 3.3 Workspace 与补丁有影响正确性的缺口

证据均在 `sdk/fix.py`：

| 问题 | 当前行为 | 影响 |
|---|---|---|
| 分析/改码版本可能不同 | 分析读当前工作区，worktree 从 HEAD 建立（64-79） | dirty 工作区下，方案针对版本与编辑版本不同 |
| 不安全复用旧执行状态 | 路径存在即返回（76-77） | 上次失败编辑、旧基线、旧票残留进入本次结果 |
| 多仓修复不成立 | 只检查 workDir 是 Git 仓（65-73），run.py:170 不按 repoRoots 建隔离 | 多仓容器目录可能成功分析但无法改码 |
| 新增文件遗漏 | 只取 git diff --binary（90-99） | untracked helper/test 不在 patch，补丁可能不完整 |
| 工单标识碰撞 | 字符替换并截断（53-55） | a/b 和 a:b 同名，可能复用 worktree 或覆盖 patch |

优先引入 runId + ticketId 摘要 + repoId + baseSha 的执行标识；实际 repo root 与目标文件绑定；验证 worktree 身份/HEAD/干净状态；按 repo 收集修改、删除、重命名和允许新增的文件。分析、编辑、验证使用同一冻结基线。对脏工作区明确采用受控快照或报告基线不匹配，不静默切换版本。

Git worktree 只是版本隔离，不提供命令执行隔离。新增执行能力时还需要独立 workspace/容器或受控 runner。

### 3.4 分析到编辑的交接丢失关键上下文

AnalyzeRequest 已含 observed/expected/steps、intentRationale、架构、specAtlas、软候选等；这部分不是从零开始。

但 fix prompt 只有 defectId、title、analysis 字典（`sdk/fix.py:212` 附近）；没有分析过程中实际读到的代码证据、调用链、替代假设、完整规格引用及环境探测结果。报告里的 ticket 切片有部分摘要，仍不等于完整证据交接。

另一方面，BatchTicket 本身没有原始 description、附件、日志、截图引用；上游蒸馏丢失的事实无法由 Agent-3 恢复。多仓 gitHead、fingerprint、partial、techStack、capabilities 等也未完整进入 AnalyzeRequest。

建议交接 EvidenceBundle：原单/附件引用、现象和验收条件、repo/baseSha、已读文件/符号/片段哈希、调用链、根因假设与反证、规格依据、变更范围、测试入口和剩余疑问。无需传整段 transcript，更不需要上游会话记忆。

### 3.5 根因可信度与路径净化仍偏弱

`contracts/bugfix_contracts/analysis_report.py:60-69` 的根因只有 summary/ruledOut/openQuestions，缺少证据定位；`sdk/analyze.py:314` 接受模型 confidence。路径存在只证明文件存在，不证明模型读过、符号存在或机制正确。

此外 `sdk/analyze.py:336-346,373` 将 shell/host/route_table 角色的精确路径直接过滤。作为抑制入口噪声的默认策略有价值，但路由分发、入口初始化、微前端注册本身也可能是真正 bug。建议改为“无直接证据时不接受为最终修位点”；有源码和复现证据时允许例外。

建议区分 symptomLocation、causeLocation、editTargets，关联 evidenceRefs；由执行层校验路径边界、版本、符号和 diff 一致性。confidence 至少拆成定位/根因/修复/验证维度，后续用标注集做校准，不把模型自报 high 当结论。

### 3.6 检索新鲜度、预算和失败隔离

- CodeGraph 已有 DB 不一定 refresh，pending 状态仍可 ready（`sdk/codegraph.py:459-488`），而 analyze prompt 要求将其片段当作已读并减少重搜。建议索引绑定 SHA/工作区摘要；过期时降级，编辑前以当前源码核实关键证据。
- AnalyzeRequest.max_turns 默认 24，resolver 一收到该默认值便不读环境覆盖（`sdk/analyze.py:36,70-75,156`）。先修配置链路，再评估按难度分配预算。
- 单票 schema 有末端兜底，但 runner/worktree/patch 写盘异常未全部票级隔离（`agents/analyst/run.py:122-213`）；父图重试整段可能重做已完成票。需要票级执行记录、幂等 artifact 与恢复点。
- 多仓同名 overlay skill 在全局按名字覆盖（`sdk/skill_inject.py:144-163`），所有票得到相同组合。应按目标仓/包选技能，保留来源；公共 SOP 共享，仓规则不互相覆盖。

## 4. 开源实现：借鉴具体机制

本次检查官方仓库、配置、核心源码或项目官方文档；不是仅收集排行榜。不同模型、任务、预算下分数不直接可比，不据其推算本项目提升幅度。

| 实现 | 核查内容 | 对本项目的借鉴 | 不宜照搬 |
|---|---|---|---|
| mini-SWE-agent | default.py 的 action/observation 循环、逐步保存 trajectory、预算；swebench.yaml 的复现→编辑→复验 | 简单内环即可；观测与失败反馈应可回放 | benchmark 假定环境已就绪；禁止提交测试是评测配置，不是产品规则 |
| SWE-agent | default.yaml 的复现流程和提交前复核 | 改动后重跑复现、diff 审核、结构化命令结果 | Python benchmark 的配置不能直接充当 Vue/Electron 业务验收 |
| Agentless | README_swebench.md 的文件→元素→行级定位、复现/回归、rerank | 层次定位；测试筛选候选；复现先在原版本确认失败 | 默认生成大量候选和测试成本过高，不宜全票套用 |
| AutoCodeRover | README 的 AST结构检索、可选频谱定位 | 文件名检索失败时进入符号/调用链；运行证据辅助定位 | Python 类/方法 API 不能直接覆盖 Vue模板、IPC、微前端边界 |
| OpenHands SDK | workspace、condenser README、stuck_detector.py | 执行环境分离；事件日志；压缩上下文仍保留近期观测；检测重复无进展 | 不需要为几个功能整体替换 Claude SDK |
| Trae Agent | agent_prompt.py 的复现、诊断、最小修改、复验、回归；Docker/trajectory 文档 | 修复完整生命周期；工具支持流程；保存失败轨迹 | 强制每票生成可执行复现不符合无实机的现实 |
| Aider | 官方 Repository map 文档 | 按当前任务和 token预算选择符号/依赖上下文 | 不要每票灌整个仓图或所有规格 |
| Sentry Seer（产品设计对照） | 当前官方文档的遥测上下文、根因/方案、外部编码 Agent交接 | 原始错误信号和证据包是重要优势；分析与编辑分离可保留 | 本项目常没有 stack/trace；不能假设拥有同等输入。仓内 Seer 快照也不能当作当前服务完整源码 |

源码与文档链接见文末。上述实现支持“执行反馈、上下文质量、候选验证值得研究”的判断；并不证明更多子 Agent、更长推理或更多采样必然提高本项目效果。

## 5. 建议的 Agent-3 形态

有三种可行路线：

1. 继续强化静态报告与一次编辑：改造小，适合完全无环境，但执行错误仍难发现。
2. 全票完整 sandbox 修复：反馈最完整，但设备、后端、老工具链和实机能力未必可提供，成本也高。
3. **推荐：证据驱动分析 + 按能力启用的修复内环。** 保留产品边界，静态模式可交付；环境允许的票执行复现和回归。

以下是建议形态，不代表已选定并批准实施：

```text
读取 batch/knowledge → 校验基线与输入 → 按票裁剪 ContextBundle
  → 定位/取证 → 根因假设 + 验收条件 → 分析质量校验
     ├─ 信息/设计/实机证据不足 → 完整阻断报告
     ├─ 未开启 applyFix → 完整分析报告
     └─ 可行动 → 隔离 workspace
          → 能力探测 + 基线检查
          → 可用时复现/构造验证用例
          → 编辑 → diff/语法/类型/范围检查
          → 可用时复验 + 相关回归
             ├─ 产品失败 → 原始失败观测回灌 → 修正或换假设（有限次）
             ├─ 环境失败 → 停止无效重试 → 未验证补丁/阻断说明
             └─ 通过 → 只读审查 → 收集完整 patch 与验证记录
```

阶段可由少量确定性状态加一个 SDK 交互内环实现，无需每个箭头都建立新 Agent/会话。分析与编辑保持分离，但编辑必须能看到证据包；测试反馈直接作用于编辑，不必每次重跑上游。

### 5.1 更充分消费 Agent-1

- 保留 rawTicketRef、日志/截图/附件引用与内容哈希；蒸馏字段附原文来源，区分事实、推断和缺失。
- intentSource/intentConfidence/expectQuality 影响验证策略，不能都当确定规格。例如 inferred expected 需对照文档，不可据此发明行为。
- 同簇票可共享检索缓存和相似症状线索，但簇不是相同根因的证明；每票保留独立假设与验收。
- needs_info 仍默认不烧 SDK；若以后支持补证据，应由明确的可得附件/日志触发恢复，不盲目搜索整仓猜需求。

### 5.2 更充分消费 Agent-2

- 将 repoRoots/gitHead、架构角色、绑定关系、规范索引和候选来源作为可验证起点。
- 仓级静态信息缓存，票级只取相关模块、调用边界、规格片段和候选；必要时再展开。
- 检索顺序可为：票中特征词/错误码/i18n key → 模块和符号 → 调用者/被调用者 → IPC/接口/路由边界 → 相关测试与历史相似修复。
- 明确记录搜过的范围、否定结果和图索引新鲜度，避免重复盲搜。CodeGraph 不可用时仍可继续。
- 不把“候选 ≤3”误用为 Agent-3 搜索空间上限；也不把 shell/host 角色误用为永久禁止修改。

### 5.3 按能力验证，而不是统一 npm test

| 能力 | 应做 | 可以声称 |
|---|---|---|
| 只有源码 | 证据审核、diff边界/完整性、可用的语法检查 | 补丁已生成；未运行验证 |
| 有编译器/类型工具 | 项目实际支持的定向 typecheck/build/lint，区分原有失败 | 指定静态检查通过；不等于行为已修复 |
| 有可运行单元/契约测试 | 原版有效失败复现，补丁后同一用例通过，相关原有测试保持 | 对该复现与回归范围验证通过 |
| 有浏览器/服务 | 固定路由、视口、语言、数据；交互断言，必要时截图差异 | 指定UI场景验证通过 |
| 依赖实机/设备/生产数据 | mock IPC/协议契约覆盖可证部分；输出剩余实机步骤 | 契约检查通过；实机行为待验证 |

验证命令优先来自 package.json、CI、README 和仓规则，并记录 cwd、runtime版本、超时、退出码、输出摘要、artifact、前后代码摘要。无法运行不伪装通过；命令退出 0 但未运行目标测试、全跳过、只检查无关文件也不能算验收通过。

复现用例应在补丁前定义并在原版运行，检查失败与工单现象相符，不能把缺依赖/语法错当成复现成功。补丁后复用相同断言，不能通过删用例或放宽断言获得绿灯。独立保留评测用 oracle，避免生成修复和生成测试共同迎合错误假设。

原有环境设计 `2026-10-22-environment-adapter-and-capability-degradation.md` 的“复现/观察/判定”三问可复用；不需要恢复整套旧 TS 接口或重建通用适配平台。

### 5.4 修复内环与审查

- 每次反馈要带失败断言/日志片段和前后差异，区分环境、产品失败和 flaky。
- 建议初始上限为 2–3 次有效回修；不是机械换三个补丁。同一假设连续被反证时回到定位，保存已排除项。
- 轻量 lint/typecheck 可在编辑后立即运行，但最终验收由确定性 runner 执行并落盘；模型不能自报通过。
- Reviewer 看原单、规格、根因证据、diff和验证结果，重点找错修位点、吞异常、默认值掩盖、破坏IPC/API契约、遗漏语言/分支、无关改动。允许退回一次；不能无上限互相挑错。
- reviewer 的判断是辅助证据，不是正确性 oracle。缺测试时其价值应通过盲审/真实历史票回放验证。

### 5.5 多候选与预算分配

先实现单轨迹的反馈循环。之后只对“已有可信验证器但首次失败”或“确有两个竞争根因”的困难票考虑 2–3 个隔离候选。

选择顺序：验收/回归证据 → 业务契约与审查 → 风险/范围 → 在满足条件者中选择较小改动。小 diff 本身不是正确性的证明；没有有效验证器时多数投票也可能只是多数重复同一误解。

模型/预算应在固定工单集上实验：更强分析模型、同模型更高预算、重试、双候选分别比较。度量每个真实解决问题的总成本，不仅单次调用成本；不预设便宜编辑模型会更划算。

## 6. 数据与评测需要同步升级

现有 G0/G1/G2/G3 适合报告路径冒烟，不能证明修复效果。尤其：

- `packaging/eval_agent3.py:94-101` 用 notes 文本判断 SDK来源；没有独立工具/会话记录。
- `:78-128` 不检查磁盘中的候选/targetFiles，虽然评测文档要求检查。
- `:162-183` 空 cases 可进入 usable_pending_g3；G3人工评分未进入汇总。
- 路径前缀真值可能仅来自工单关键词 grep，命中目录不等于找到根因。
- 当前 apply-fix 测试主要注入 fake runner，不能证明真实 workspace/patch 生命周期。
- 实仓跑批产物在仓外，本次没有可核验的真实修复成绩，不能声称当前已经达到某成功率。

建议建立两套互补评测，保留并扩展现有报告评测，不再混成一个“可用”标签：

**A. 冻结的分析集**：固定 batch、knowledge、repo SHAs、模型、prompt/skills版本。覆盖设备Web/Electron/微前端、强/弱/空候选、完整/缺失原单、实机依赖、不可定位/非代码。

**B. 历史已修缺陷回放集**：回到真实修复前基线，只给当时可见的信息；gold patch/后续PR/隐藏测试不给 Agent。用独立验收、开发者盲审和回归评估。按时间与代码模块留出测试集，避免调prompt时反复看同一批票。合成缺陷用于边界覆盖，不能替代真实票成功率。

建议先建立约 30–50 条可复核样本，再逐步扩大；每仓型保留足够案例。该数量是启动建议，不代表统计显著性保证。昂贵策略比较需要多个重复run，报告不确定性。

| 指标 | 用途 |
|---|---|
| 端到端解决率（全部输入票为分母） | 防止通过排除难票提升表面数字 |
| 可修票解决率与错误改码率 | 同时看召回与错误行动，防止过度保守或乱修 |
| Agent-3 相对 Agent-2 的 loc@k 增量、符号/机制真值 | 区分找到目录与找到原因 |
| patch可应用/新增文件完整/基线一致 | 补丁工程可靠性 |
| 复现有效率、前失败后通过、相关回归保持率 | 行为证据 |
| 未验证patch接受率、后续补改量、退回原因 | 无环境路线的实际价值 |
| 环境阻断/信息阻断/模型失败/预算触顶分布 | 定位损失来源，不能把阻断隐藏 |
| 同票重复run稳定性、错误high-confidence率 | 可信度与稳定性 |
| 每解决一票总成本、token/时间、p95延迟 | 质量与成本取舍 |

每次实验固定同一上游输入。依次消融：基线 → 门禁/workspace修复 → 证据交接 → 上下文裁剪/检索 → 可选验证内环 → reviewer → 多候选。分别在有环境和无环境子集比较。不要在一次实验里同时换模型、仓图、prompt、技能与预算。

## 7. 建议实施顺序

| 优先级 | 工作 | 相对成本 | 验收重点 |
|---|---|---|---|
| P0 | 根因状态门禁，禁止占位/跳过分析进入fix | 小 | heuristic、limit耗尽、partial不能误改；静态证据足够的正常票仍能改 |
| P0 | 多仓基线与worktree身份、新文件补丁、范围校验 | 中 | 重跑/碰撞/新增文件/跨仓/失败恢复覆盖，不串票、不漏文件 |
| P0 | 可信评测和执行证据 | 中 | 空集拒绝、覆盖率/唯一ID、真实路径与patch检查、G3与失败run可追溯 |
| P1 | ContextBundle/EvidenceBundle、结构化根因 | 中 | 编辑基于同一基线和可核对机制，减少交接丢失 |
| P1 | 能力探测与可选静态/定向测试runner、有限回修 | 中至大 | 有能力时真实反馈，无能力时诚实降级；不强制启动完整业务环境 |
| P1 | 检索新鲜度、按仓技能、票级持久化与恢复 | 中 | 不读旧索引、不串规范、不因一票重跑整批 |
| P2 | 独立reviewer、难票2–3候选、预算/模型路由 | 中 | 同一冻结集上证明净收益，并计入成本/延迟 |
| P2 | 浏览器/设备探针与更完整CI反馈 | 大且仓相关 | 针对实际高频缺陷建立有效验收，而非形式化跑命令 |

如果只做第一轮：优先修门禁和workspace，补分析到编辑的证据交接，在一个依赖可满足的目标仓打通“有效复现→最小修复→复验/回归→有限回修”，同时保留另一类无环境票的未验证补丁路径。两条路线都用同一评测标准衡量真实价值。

## 8. 外部来源

以下链接为本次读取来源；main分支会变化，若进入实施应固定所借鉴文件的commit。

1. mini-SWE-agent [核心循环](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py)、[SWE-bench配置](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/config/benchmarks/swebench.yaml)。
2. SWE-agent [默认配置与提交复核](https://github.com/SWE-agent/SWE-agent/blob/main/config/default.yaml)。
3. Agentless [完整定位、复现、回归、候选选优流程](https://github.com/OpenAutoCoder/Agentless/blob/main/README_swebench.md)。
4. AutoCodeRover [项目结构检索与测试增强](https://github.com/AutoCodeRoverSG/auto-code-rover/blob/main/README.md)。
5. OpenHands SDK [运行架构](https://github.com/OpenHands/software-agent-sdk/blob/main/README.md)、[上下文压缩与事件日志](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/context/condenser/README.md)、[重复无进展检测](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/stuck_detector.py)。
6. Trae Agent [系统流程](https://github.com/bytedance/trae-agent/blob/main/trae_agent/prompt/agent_prompt.py)、[Docker与轨迹](https://github.com/bytedance/trae-agent/blob/main/README.md)。
7. Aider [Repository map](https://aider.chat/docs/repomap.html)。
8. Sentry [Seer官方设计说明](https://docs.sentry.io/product/ai-in-sentry/seer/)。本次公开 getsentry/seer 地址未能取得源码，Seer对照基于官方产品文档与仓内既有快照，不声称完成当前实现审计。
9. SWE-bench [独立评分规则](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/grading.py)。借鉴前失败后通过与回归保持的验证原则，不引入其适配器，也不把隐藏测试/修复答案作为Agent可见上下文。
