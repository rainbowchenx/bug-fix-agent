# Agent-3 修复与反馈闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**日期：** 2026-11-15（Asia/Shanghai）。状态：M3 实现完成（`feat/agent3-repair-feedback`），未提交。

**Goal:** 在当前代码上交付可核实的单票修复、全量报告和用户反馈续修，优先提高修复正确性。

**Architecture:** 复用 Python/LangGraph 编排、Pydantic 契约和 Claude Agent SDK。逐票状态存为 JSON，使用隔离工作副本、受控检查命令、阶段提交和单写入锁；模型做机制判断，程序校验来源、版本和产物。

**Tech Stack:** Python >=3.11、Pydantic >=2.7、现有 LangGraph/SDK 可选依赖、Git、pytest；首期不新增数据库。

**Spec:** [修订设计](../specs/2026-11-15-agent3-repair-feedback-design.md)。依据：[复审记录](../../research/2026-11-15-agent3-design-review.md)、[讨论](../specs/2026-11-13-agent3-direction-discussion.md)。执行前必须同时阅读。

## 全局约束

- 无旧契约兼容要求；新版本明确校验，不用默认值把旧产物伪装成新证据。
- 用户自行应用/验收；不自动提交、推送、合并、部署或修改用户源工作区。
- 无实机环境允许候选补丁；检查失败归因和未验证范围必须准确。
- Agent-2 保留逐票调查；缺信息不自动禁止调查；结构完整不证明机制正确。
- 普通源文件新增/修改/删除补丁完整；特殊 Git 类型不支持时明确阻断。
- 默认 analyze-only；generate-patch 显式开启。没有运行结果不能填写 passed。
- 首期单写入、文件反馈、阶段恢复；不建设数据库、全仓依赖图或自动反馈队列。
- 当前工作区已有大量修改。执行前登记状态，不能整仓覆盖、重置或将既有改动混入提交；本计划不安排自动提交。

## Review Focus

1. 新 helper 尚不存在：不能因未读目标文件误拒，也不能遗漏新增文件补丁（T04/T05）。
2. HEAD 不变而用户修改文件：必须识别实际内容及旧补丁部分应用（T03/T12）。
3. 同样“仍未解决”来自两轮测试：不能按文本内容吞掉新反馈（T11）。
4. 编译通过但修复只是隐藏错误：必须语义复核；原基线也通过的测试不算修复证明（T07）。
5. 旧索引/入口文件/缺图票：不误排真正修复点，不假装看过附件（T02/T04/T09）。

## 文件边界与共享接口

新增模块放在 `platform/bugfix_platform/agents/analyst/`：`context.py` 组装任务上下文、`evidence.py` 校验证据/门槛、`workspace.py` 管理 Git 快照与差异、`checks.py` 管理检查执行、`attempt_store.py` 管理文件提交与锁、`feedback.py` 管理反馈与补丁关系、`sessions.py` 决策恢复、`report.py` 确定性渲染。保留 `run.py` 为应用入口，`sdk/analyze.py`、`sdk/fix.py` 为模型适配层，不再把 Git/存储/检查逻辑塞入 prompt。

契约定义于 `contracts/bugfix_contracts/analysis_report.py` 及新增 `repair.py`；输入与知识扩展分别落在现有 defect_batch.py、code_knowledge.py。逻辑对象以 attempt 文档嵌套保存，不为每个对象建立独立服务。

核心数据名统一：TaskContext、Evidence、EditDecision、WorkspaceSnapshot、PatchSet、VerificationRun、AttemptRecord、Feedback、SessionDecision。T01 定义字段，后续任务只能引用同名类型，不另建同义字典。

## 优先级、依赖与里程碑

| 任务 | 优先级 | 硬依赖 | 交付 |
|---|---|---|---|
| T00 | P0 | 无 | 基线、环境与验证命令 |
| T01 | P0 | T00 | 新契约与状态不变量 |
| T02 | P0 | T01 | 输入保真、附件可访问 |
| T03 | P0 | T01 | 实际基线与逐仓工作副本 |
| T04 | P0 | T01,T02 | 分析上下文与证据门槛 |
| T05 | P0 | T03,T04 | 完整普通源文件补丁 |
| T06 | P0 | T03,T05 | 工程检查与执行证据 |
| T07 | P0 | T04,T05,T06 | 语义复核和有限回修，M1 |
| T08 | P1 | T01,T04 | Agent-2 调查覆盖与交接 |
| T09 | P1 | T04,T06 | 技能完整读取与实际使用记录 |
| T10 | P0 | T01,T07 | 全量报告、逐票持久化，M2（同时集成T08/09） |
| T11 | P1 | T10 | 文件反馈导入 |
| T12 | P1 | T03,T11 | 旧补丁识别与代码变化复核 |
| T13 | P1 | T04,T10,T12 | 会话续接/新开与反馈执行，M3 |
| T14 | P0 | T07起持续，最终T13 | 可信评测与首期验收 |

P0 表示正确性交付门槛，P1 表示完整首期所需后续能力，不表示可永久省略。M1 可内部评估，M3 才是首期反馈闭环。任务按依赖推进；共享契约和 run.py 的改动需串行集成。


## T00：记录当前基线与执行环境

**文件：** `pyproject.toml；tests/helpers.py；新增 tests/platform/repair_cases/README.md`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** 无新业务接口；输出版本/模型/预算/输入摘要的基线清单。

- [x] 先增加本任务行为测试，断言：现有测试失败先归因；没有真实验收数据不生成成功率。
- [x] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [x] 实现：记录 git 状态、Python/依赖可用性；复用现有测试入口，不在业务仓安装依赖。选择参数传反、失败状态遗漏、需要补图、不属于仓库四类夹具，保留当前输出及限制。
- [x] 验证：`python -m pytest tests/contracts tests/platform/test_agent3_sdk_report.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T01：定义新契约与可校验不变量

**文件：** `contracts/bugfix_contracts/{repair.py,analysis_report.py,defect_batch.py,code_knowledge.py,common.py,__init__.py}；tests/contracts/test_repair_contracts.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** 新增上述共享类型；validate_edit_decision(context: TaskContext, decision: EditDecision) -> list[str] 在T04实现。

- [ ] 先增加本任务行为测试，断言：candidate必须有完整patch引用；passed必须有执行记录；accepted只能由反馈写入；旧版本明确拒绝；嵌套结构可JSON往返。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：定义输入revision、来源类别、证据有效性、基线、补丁替代/追加关系、逐项检查与用户应用/验收维度；统一升级 schemaVersion 并同步样本。
- [ ] 验证：`python -m pytest tests/contracts -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T02：保留原文与附件，纠正预期质量

**文件：** `agent1/bugfix_agent1/{ingest/field_map.py,defect_batch/distill.py,defect_batch/cluster.py,defect_batch/expect_quality.py}；analyst/context.py；tests/agent1/test_repair_provenance.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** build_task_context(ticket, knowledge, revision, snapshot) -> TaskContext。

- [ ] 先增加本任务行为测试，断言：原始票可追溯；模板错位不得当明确验收；缺图不杜撰；部分坏行和重复ID都有去向；原始字段不丢。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：保留原文/字段来源/附件稳定引用和输入清单；区分非空预期与相关预期，冲突不抹除；记录图像是否实际读取，不能只凭文件名推断。
- [ ] 验证：`python -m pytest tests/agent1/test_repair_provenance.py tests/agent1/test_defect_batch_fixtures.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T03：实现实际代码快照与逐仓隔离

**文件：** `analyst/workspace.py；sdk/fix.py；tests/platform/test_repair_workspace.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** capture_workspace(repo_root: Path) -> WorkspaceSnapshot；prepare_workspace(snapshot, destination: Path) -> Path。

- [ ] 先增加本任务行为测试，断言：HEAD相同dirty不同可区分；复制时变化拒绝错基线；不同票ID不碰撞；失败残留不复用；源目录内容不改变。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：为多仓容器解析真实目标仓；采集HEAD、dirty和必要untracked；重放到隔离副本并校验，排除凭据/依赖；同批可复用不可变基线。
- [ ] 验证：`python -m pytest tests/platform/test_repair_workspace.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T04：修正分析与改码门槛

**文件：** `analyst/{context.py,evidence.py,route.py,run.py}；sdk/analyze.py；sdk/codegraph.py；tests/platform/test_repair_evidence.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** validate_edit_decision(context: TaskContext, decision: EditDecision) -> list[str]；空列表才可编辑。

- [ ] 先增加本任务行为测试，断言：占位/未调查/失效证据不能编辑；新增文件核对调用方可通过；路由真根因不误拒；旧图必须读当前文件；环境预算覆盖默认值；机制语义仍由模型解释。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：传原文、最强线索、规范和有效证据；校验引用/当前源码；去掉入口硬排除和图强制优先；记录有效预算；缺信息可有限补证；预留收尾预算。
- [ ] 验证：`python -m pytest tests/platform/test_repair_evidence.py tests/platform/test_analyze_sdk.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T05：生成完整且可应用的补丁

**文件：** `analyst/workspace.py；sdk/fix.py；tests/platform/test_repair_patch.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** collect_patch(snapshot: WorkspaceSnapshot, worktree: Path) -> PatchSet。

- [ ] 先增加本任务行为测试，断言：新增helper不漏；删除/重命名等价差异完整；空diff不候选；特殊类型未支持明确拒绝；dirty前提被标注；绝不将源仓预存改动打包。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：编辑取得TaskContext及EditDecision；临时索引或快照差异捕获新增/删除；比较输入副本到最终内容，排除用户原有修改；在等价基线验证应用。
- [ ] 验证：`python -m pytest tests/platform/test_repair_patch.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T06：提供受控验证执行

**文件：** `analyst/checks.py；sdk/fix.py；tests/platform/test_repair_checks.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** run_check(spec, workspace: Path, timeout_seconds: int) -> VerificationRun。

- [ ] 先增加本任务行为测试，断言：缺依赖/凭据为blocked；超时终止自身进程；宿主模式不宣称强隔离；源仓变化检测可见；建议步骤不会记passed；依赖不自动升级。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：检查规格含命令参数、cwd、后端、超时、环境与覆盖；执行项目已有相关单测/语法/类型/编译；明确配置宿主命令或复用现成隔离；记录退出码日志和实际候选摘要。
- [ ] 验证：`python -m pytest tests/platform/test_repair_checks.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T07：语义复核与有限回修

**文件：** `analyst/run.py；sdk/{analyze.py,fix.py}；tests/platform/test_repair_loop.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** run_ticket(context: TaskContext, services) -> AttemptRecord；services注入分析/编辑/检查/保存函数。

- [ ] 先增加本任务行为测试，断言：隐藏错误/删断言不能作为合格候选；测试基线已通过不算修复证据；回修后旧检查失效；错误方案可返回调查；无实机但静态依据充分可交付未实测候选。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：最终diff对照预期与正常/失败/重试行为；新增用例尽可能基线失败候选通过；最多3次候选迭代且预算可提前结束；新歧义返回调查；检查引入失败归diagnostic。
- [ ] 验证：`python -m pytest tests/platform/test_repair_loop.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T08：修正Agent-2逐票覆盖与事实交接

**文件：** `sdk/cartography.py；agents/cartographer/{run.py,match.py}；tests/platform/test_cartography_coverage.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** 每票investigationStatus、evidence、searchedScopes、hypotheses、openQuestions进入CodeKnowledge。

- [ ] 先增加本任务行为测试，断言：超过16票无静默假完成；零候选合法；source不代替因果证据；同组三控制器底稿不会统一伪装已调查；批次预算耗尽明确未调查。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：将16票单次截取改成配置小批与显式剩余覆盖；失败批只标相关票；弱词面候选标底稿；程序核对路径/片段，模型不凭空填满；分组共享仓知识。
- [ ] 验证：`python -m pytest tests/platform/test_cartography_coverage.py tests/platform/test_cartography_sdk.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T09：修复技能加载与使用观测

**文件：** `sdk/skill_inject.py；analyst/context.py；platform/skills/；tests/platform/test_repair_skills.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** 技能键(source, repoId, name, version)；TaskContext包含选择及使用证据。

- [ ] 先增加本任务行为测试，断言：正文超过2400字符关键步骤不丢；同名多仓不污染；selected不等于applied；依赖缺失不假称执行；第二轮重新判断适用性。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：复用发现流程，正确解析YAML多行描述、按仓作用域处理同名、完整读正文/支持资源；先精选方法技能并固定来源许可；图像/浏览器依赖按工具可用性决定。
- [ ] 验证：`python -m pytest tests/platform/test_repair_skills.py tests/platform/test_analyze_skill_inject.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T10：全量报告与可靠阶段落盘

**文件：** `analyst/{attempt_store.py,report.py,run.py}；workflow/{persist.py,graph.py,state.py}；http/{store.py,runner.py,models.py}；cli.py；tests/platform/test_repair_report_store.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** save_attempt(root: Path, attempt: AttemptRecord) -> Path；render_report(report) -> str；load_attempt(path: Path) -> AttemptRecord。

- [ ] 先增加本任务行为测试，断言：排除/重复/失败/未调查全部有去向；计数吻合；写失败不可称成功；渲染失败可重建不重编辑；崩溃只恢复完整阶段；第二writer返回busy且不覆盖。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：先登记全量输入；逐票异常隔离；关键文件先写后提交attempt；latest可重建；JSON和Markdown同源；补丁相对链接；移除openMr假交付；同目录单写入锁。
- [ ] 验证：`python -m pytest tests/platform/test_repair_report_store.py tests/platform/test_http_runs_api.py tests/platform/test_langgraph_workflow.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T11：反馈文件导入

**文件：** `analyst/feedback.py；cli.py；tests/platform/test_repair_feedback.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** import_feedback(root: Path, feedback: Feedback) -> InputRevision。

- [ ] 先增加本任务行为测试，断言：同ID重复不创建两轮；相同文字不同ID保留；未应用/部分应用/手改/未知均合法；过期反馈不覆盖最新验收；无后台自动执行。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：CLI增加feedback子命令，参数为报告根和反馈JSON文件；解析票/轮次/补丁引用，未知先保存；按feedbackId幂等；错误引用不猜最新版本；报告附模板。
- [ ] 验证：`python -m pytest tests/platform/test_repair_feedback.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T12：核实旧补丁和证据失效

**文件：** `analyst/{feedback.py,evidence.py,workspace.py}；tests/platform/test_repair_continuation.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** classify_patch_state(patch: PatchSet, snapshot: WorkspaceSnapshot) -> application状态及依据。

- [ ] 先增加本任务行为测试，断言：HEAD相同但部分应用准确识别；HEAD变化不能盲目全丢或全信；反向apply检查不是唯一依据；无法确认不重复应用；新验证关联实际候选。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：综合内容与已知补丁差异判定，歧义保留unknown；新attempt重新裁决；相关调用方/配置变化待复核；未应用产替代版，已应用产当前基线增量，手改不回滚。
- [ ] 验证：`python -m pytest tests/platform/test_repair_continuation.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T13：会话恢复与二次执行入口

**文件：** `analyst/sessions.py；sdk/{analyze.py,fix.py}；cli.py；tests/platform/test_repair_sessions.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** choose_session(context: TaskContext, previous: AttemptRecord | None) -> SessionDecision。

- [ ] 先增加本任务行为测试，断言：缺会话仍可继续；cwd最近会话不被使用；SDK不支持resume不得静默假恢复；补信息解除旧needs_info；补丁被否定可改变路线；首期反馈完整闭环。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：显式sessionId映射到票/阶段；同方向兼容可resume；大变化/不可得新开；fork不共享写目录；CLI resume子命令指定票和已导入revision；恢复包显式新增/失效事实。
- [ ] 验证：`python -m pytest tests/platform/test_repair_sessions.py tests/platform/test_repair_continuation.py -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## T14：升级评测并完成首期验收

**文件：** `packaging/eval_agent3.py；docs/field-eval/agent3/README.md；tests/platform/test_eval_agent3.py；tests/integration/test_repair_feedback_flow.py`（省略前缀 analyst=platform/bugfix_platform/agents/analyst，sdk=platform/bugfix_platform/sdk；未存在文件为新增）。

**接口/交付：** score_report明确analysis/patch模式，使用实际证据和输入清单。

- [ ] 先增加本任务行为测试，断言：去掉needs_info调用SDK判错和notes执行证明；三条端到端：缺信息补足、拒绝候选纠正、应用后追加；未反馈不算成功；成本和分母明确。
- [ ] 执行下列命令，确认新增测试因缺少目标行为失败；记录原有失败，不用无关异常冒充有效失败。
- [ ] 实现：拒绝空样本和重复真值；全量覆盖；分析/修复模式分别评分；机制人工审阅与运行检查分开；固定模型预算做前后对照；后续三项目材料随到随评。
- [ ] 验证：`python -m pytest tests/contracts tests/agent1 tests/platform tests/integration -q`；预期新增与相关回归测试全部通过。
- [ ] 复核diff仅含本任务修改，更新计划勾选与证据；如获提交授权，只提交本任务文件，禁止顺带提交既有改动。

## 执行前检查与验收出口

- [ ] 执行T00时先确认当前Python与依赖；若pytest环境缺失，在项目专用虚拟环境安装已有dev/platform/sdk依赖并记录版本，不改变系统Python。SDK确切版本在真实smoke前固定，不在本计划猜测API可用性。
- [ ] M1：T01—T07通过；真实临时Git仓上的候选可应用，源仓无变化；正常修复与拒绝错误修改都有行为证据。此时只能称单票链路完成。
- [ ] M2：集成T08—T10；大于16票输入覆盖明确；每张输入票有报告去向；一票失败不终止其余；报告、补丁、检查记录可追溯。
- [ ] M3：T11—T14通过；用户文件反馈可驱动下一轮，旧补丁关系正确，缺SDK历史仍可新开继续；关键持久化失败明确。
- [ ] SDK真实smoke单独使用可丢弃夹具仓和明确模型预算，验证工具/会话/技能可见性；离线fake runner测试不代替该项。无凭据时标为未执行，不能说真实模型链路已验收。
- [ ] 业务效果验收与工程验收分开：无三类项目真实资料时交付机制测试结果，不声称业务修复率提升；材料到达后按原票、上游输入、补丁、验收一一关联。

## 明确延后及变更控制

联合多仓编辑、二进制/特殊模式/子模块修复、数据库、后台队列、多writer、语义冲突引擎、默认独立reviewer、自研沙箱不属于首期验收依赖。多仓容器中单目标仓定位/修复属于T03/T05必备。需要延期能力才能修复的票报告具体限制，不包装成非代码缺陷。

实施者可调整局部函数拆分；改变状态语义、默认行为、依赖边界或用户交付流程时先修订设计与本计划。完成测试不是自动获得远端发布或部署授权。

## 计划自查记录

2026-11-15：按设计逐节映射：职责/输入=T02/T08；流程/门槛=T04/T07；调查预算=T04；契约=T01；Git/补丁=T03/T05；验证=T06/T07；技能=T09；会话=T13；反馈=T11/T12；报告/落盘=T10；评测=T14。Review Focus五类均有归属任务。每项包含文件、接口、依赖、行为断言与运行命令。所有复选框保持未完成，本轮未运行这些未来实现测试。

2026-11-15 晚：T00–T14 行为测试与实现已合入 `feat/agent3-repair-feedback`。`py -3.12 -m pytest tests/contracts tests/agent1 tests/platform tests/integration --ignore=tests/platform/test_sdk_billing.py` → 301 passed, 7 skipped。`test_sdk_billing.py` 4 条仍因环境无 `claude-agent-sdk` 失败（T00 已归因，非本计划回归）。无提交授权，未做 git commit。SDK 真实 smoke 未跑。

2026-11-15 夜：`py -3.12 -m pip install -e ".[dev,sdk]"` 装上 `claude-agent-sdk==0.2.182`。全量 `tests/contracts tests/agent1 tests/platform tests/integration` → **312 passed, 5 skipped**（含 billing；HTTP 同步 run 补了 `.git` 夹具）。真实 SDK smoke（device-web 1 票、max_turns=6）：会话拉起、CodeGraph MCP 工具名可见、attempt/md 落盘。第一次 401（DeepSeek key 放在 `ANTHROPIC_API_KEY`）；进程内改走 `ANTHROPIC_AUTH_TOKEN` 后认证过了，但模型名 `deepseek-flash` 被拒。未改用户 `.env`。不能声称真实模型链路已验收。
