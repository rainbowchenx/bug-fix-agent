# Agent2调查保全与Agent3反馈收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

本计划制定于 2026-11-17。现有能力与待验事项以[当前实现与验收状态](../../architecture.md#验收状态)为准。

**Goal:** 消除SDK局部异常导致整票调查丢失，并使用户补充后的Agent3能继承决定、收敛问题、进入有证据的修复尝试。

**Architecture:** 复用三Agent产物、文件锁/原子写、SDK会话及现有隔离fix loop。新增少量边界模块，分别承接模型响应、组进度、逐轮快照、反馈文档和续跑上下文；不新增Agent/数据库/后台队列。

**Tech Stack:** Python >=3.11、Pydantic、现有Claude Agent SDK、LangGraph、pytest及现有CLI/HTTP。

**Spec:** [完整方案](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)。证据：[三项目复评](../../field-eval/agent3/reviews/2026-11-17-three-project-real-run-assessment.md)、[93/18统计](../../field-eval/agent3/reviews/2026-11-17-three-project-artifact-statistics.json)、[18票对照](../../field-eval/agent3/reviews/2026-11-17-three-project-ticket-comparison.csv)。前置：[11-16计划](2026-11-16-three-agent-evidence-quality-implementation-plan.md)。

## Global Constraints

- 生产契约统一0.4.0，无历史生产产物兼容层；旧归档仅离线取证。
- applyFix=false始终零编辑；反馈中的同意不代替`--apply-fix`授权。
- 身份/范围严格，非关键字段局部容错；规范化不产生valid事实或假complete。
- 原始解析输入先完整保存，落盘错误显式artifact_error；调试轨迹截断不得丢解析候选原文。
- 收到答案不等于已解决；技术选择由Agent依据现有规范决定，关键产品分歧仍可阻断。
- 每个主调用最多一次2-turn格式修复（含原有budget salvage），每票每轮最多一次2-turn决策收尾；共享剩余turn/cost/time预算，无余额不调用，不重置预算或新建review Agent。
- 新epoch/协议变更失效旧缓存；stage journal与complete cache不同，partial不能当complete复用。
- 不运行归档脚本/pickle或真实凭据测试；fake验证控制链，不证明业务理解。
- 实施前记录HEAD/dirty，保留当前评估文档；隔离实施工作树在执行阶段安排，不能丢未提交材料。不自动提交/推送；获明确授权后再做版本控制操作。
- 70%是可修业务票验收成功率的试运行提议，非工程标准或已承诺SLA；真实项目范围仅peitao/transport/hcp。

## Review Focus

1. 合法票与错/重复ID混在一组，或共享架构/最终契约坏了：保留唯一合法票与已接受字段，不整组退baseline；格式收尾也不能清空前次成果（T1/T2/T3）。
2. SDK流式途中异常、磁盘写失败、manifest/latest之间退出、组预算耗尽：收到的内容先保全，不能声称完整保存或从头反复花费（T1/T3/T5）。
3. 用户填写旧表/改绑定、并发导入/续跑、连续导入多次才执行、只改预期：正确绑定父轮、累计补充、仅失效相关决定，不丢用户填写内容（T5/T6/T7/T9）。
4. 模型遗漏旧题/换ID重问、摘要丢答案、协议坏了却报choice：完整账本、有界收尾与工程错误分类；语义改写真实验收另测（T7/T8/T10）。
5. SDK恢复失败、业务HEAD相同但dirty变化、补丁部分应用：新会话有previousAttempt、旧证据不直接授权、旧补丁不盲重放（T7/T9）。

## 优先级、依赖和里程碑

| 任务 | 优先级 | 依赖 | 独立验收交付 |
|---|---|---|---|
| T0 契约/来源夹具 | P0 | 无 | 0.4.0类型及真实证据/合成夹具边界 |
| T1 A2响应与诊断存储 | P0 | T0 | SDK实际解析原文可追，失败可定位 |
| T2 A2分层规范化 | P0 | T0/T1 | 局部异常不丢合法成果，身份不串票 |
| T3 A2状态/恢复/预算 | P0 | T1/T2 | 调查状态真实、增量恢复及账单完整 |
| T4 A2实际工具权限 | P0 | T0 | SDK执行前拦截非只读Bash |
| T5 A3逐轮分析快照 | P0 | T0 | 首轮及后续分析不可覆盖、可重建 |
| T6 用户填写与答案导入 | P0 | T5 | 无需手写JSON的反馈入口 |
| T7 previousAttempt与父轮恢复 | P0 | T5/T6 | 每种会话模式都有首轮结论与答案 |
| T8 决策事权/收敛校验 | P0 | T7 | 技术问题不全上交、已答问题有消费结果 |
| T9 正式入口/修复闭环 | P0验收 | T2/T3/T4/T6/T7/T8 | 只报告与授权修复两种入口可靠 |
| T10 评测与真实试点 | P1工程支撑、独立业务验收 | T9 | 固定分母的效果与成本记录 |

执行顺序：T0→T1→T2→T3；T4可在T0后独立实施。T5→T6→T7→T8依赖串行；共享契约和run.py修改串行集成。T9在其列明依赖完成后运行最小入口，再完整回归。T10的表单/计分可开发，真实业务材料未齐不阻塞工程交付。

M1：Agent2保全与权限可靠；M2：首轮→填答→二轮真实入口消费并进入有授权修复；M3：真实模型与业务效果通过。M1/M2不能冒充M3完成。

## 文件与接口约定

下列目录均相对仓根。新类型统一在现有contracts/bugfix_contracts/{code_knowledge,repair,analysis_report}.py，新增模块遵从方案第3节。接口名称为本方案推荐，不是现有实现；调整签名必须同步本计划的调用方。

- `normalize_sdk_match(item, *, requested_ids, raw_ref) -> MatchParseResult`返回accepted、issues、acceptedFields、rejectedFields；外层group解析先定位业务信封、按ID隔离歧义，并校验共享增强块。它不直接写业务文件。
- `InvestigationRecorder.save_response` / `save_group_progress(root, progress) -> Path`。
- `save_analysis_snapshot(root, attempt, snapshot, *, already_locked=False) -> AnalysisSnapshotRef` / `load_analysis_snapshot(root, defect_id, attempt_id) -> AnalysisSnapshot`。
- `render_feedback_form(snapshot) -> str` / `parse_feedback_form(text, *, store) -> Feedback`。
- `build_previous_attempt(root, defect_id, parent_attempt_id, current_snapshot, feedback) -> PreviousAttemptContext`。
- `consume_question_answers(previous, revision, proposed_questions, current_evidence) -> ConvergenceResult`，包括resolutions、openQuestions、violations与是否需一次收尾，不把语义冲突自行判为已解决。

### T0：冻结契约和最小回归来源

**Files:** Modify contracts/bugfix_contracts/{common,code_knowledge,repair,analysis_report,defect_batch,__init__}.py；Create tests/fixtures/repair_quality/handoff-convergence/manifest.json；Test tests/contracts/test_handoff_convergence.py。同步现有fixtures/文档属于本任务范围，不改历史ZIP。

**Interfaces:** 输出0.4.0的InvestigationFact/CodeReference、ParseIssue、MatchParseResult、RawResponseRef、QuestionAnswer/Resolution、AnalysisSnapshot/Ref、PreviousAttemptContext、ConvergenceResult；schema定义与SDK prompt共用同一字段约定。

- [ ] 写往返测试：字符串尚属不可信输入，生产Fact保持结构化；旧0.3产物明确拒绝；稳定questionId/parentAttemptId、baseRevisionId与内部parentRevisionId分工、resolutionSource/targetDigest及存储/接受状态分别校验；user_answer来源必须有answerRevisionId，自主决定不得伪造用户答案，类型缺失不被extra=ignore吞掉。
- [ ] 运行`py -3.12 -m pytest tests/contracts/test_handoff_convergence.py -q`，确认新增行为失败而非仅依赖错误。
- [ ] 固定字段/导出及最小脱敏夹具。85拒绝用计数证明故障，不伪造“85个真实响应”；字符串facts注明是已复现输入，原始错误响应仍待补。
- [ ] 同命令通过，核对common版本、各Literal、CLI/HTTP序列化、样本及SDK输入清单。
- [ ] 自审并记录任务证据；不自动提交。

### T1：SDK原始响应先保全

**Files:** Create platform/bugfix_platform/agents/cartographer/investigation_store.py；Modify platform/bugfix_platform/sdk/cartography.py、agents/cartographer/{run,investigation}.py；Test tests/platform/test_investigation_store.py。

**Interfaces:** 使用T0 RawResponseRef/ParseIssue；通过 InvestigationRecorder 在 parse/coerce 之前保存响应，SDK结果带artifact引用传给调度器。

- [ ] 写失败测试：structured_output、全部解析候选文本、result/errors、一次格式修复前后均留独立记录；坏JSON/SDK流式异常之前已收到的消息仍有原文及诊断；原始记录不可写不得标已保存/写缓存。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_investigation_store.py -q`确认失败。
- [ ] 流式增量保全，原子写manifest/响应/诊断并保存实际SDK版本、输入/仓/技能/预算摘要。调试transcript默认32MiB上限并标truncated；解析输入独立完整保存，任何无法保全的解析输入触发artifact_error。失败不更新可恢复latest，不回显秘密环境字段。
- [ ] 同命令通过；用SDK query受控消息实际走run_claude_cartography而非只调用写文件helper。
- [ ] 检查错误记录有具体fieldPath/rawRef，不只invalid_match计数。

### T2：字段及候选隔离规范化

**Files:** Create platform/bugfix_platform/sdk/match_payload.py；Modify agents/cartographer/match_payload.py、handoff.py 及 SDK prompt；Test tests/platform/test_sdk_match_normalization.py、tests/platform/test_cartography_sdk.py。

**Interfaces:** 消费T1 raw_ref，产出MatchParseResult；正式CodeKnowledge只接收类型合法内容和显式diagnostics，不从模型接收tool_observed。

- [ ] 写参数化失败测试：字符串/字典混合facts、数字/布尔/空串/null/嵌套列表、坏候选source/路径/符号、未知confidence/gap、坏可选字段、未知字段；断言其它合法内容仍保留。
- [ ] 加身份测试：同组A合法、B重复、C组外、D缺ID时，仅A交接、B全部版本隔离、C/D不猜身份；其他唯一合法票不受影响。候选越界不带走合法facts。
- [ ] 加组装/输出测试：坏architecture.modules不丢逐票调查；首个工具JSON/空structured_output不遮住有效业务JSON；收尾缺票不清空先前有效内容，冲突不first/last wins；最终总契约错误保存accepted产物及internal_error，可离线重放而非退纯baseline伪成功。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_sdk_match_normalization.py tests/platform/test_cartography_sdk.py -q`确认缺行为失败。
- [ ] 实现确定的白名单转换、字段/元素级诊断；保留字符串为unverified claim，禁止任意str()。baseline留独立来源，不能盖过成功SDK内容或冒充SDK事实。
- [ ] 完整schema进入prompt/结构化输出；输出缺关键字段最多一次2-turn收尾，沿用预算salvage配额。收尾失败交付合法残片和明确失败原因，不重新探索；离线重放不得发起SDK query。
- [ ] 同命令通过；增加按SDK实际消息协议构造的受控JSON→normalize→merge→CodeKnowledge正式链回归（本批未归档原始响应，不称真实原文），禁止仅fake runner直接返回正确类型来验证此任务。

### T3：覆盖、阶段恢复、停止和成本

**Files:** Modify agents/cartographer/{investigation,investigation_store,run}.py、sdk/cartography.py `annotate_investigation_coverage`、contracts/code_knowledge.py；Test tests/platform/test_investigation_progress.py、test_investigation_batches.py。

**Interfaces:** T2结果驱动每票接受/证据状态；新增`run_cartographer(..., artifact_dir=None, resume_dir=None, ticket_ids=None)`传递到组调度；workflow/CLI/HTTP在T9接入。正式SDK运行要求持久化目录：复用out-dir或工作流默认workDir/.bugfix-runs/<runId>/artifacts，返回根路径，源指纹排除该目录；不可写明确失败。

- [ ] 写失败测试：无引用字符串facts、仅path/符号不能complete；原文snippet与当前内容摘要核对成功也只标reference_verified，不宣称根因成立；scope模型自述不伪装实际工具轨迹；坏输出不得因ID出现而partial成功；启动后失败/漏票不用not_investigated伪装从未启动；互斥阶段计数可对齐planned唯一票数，launched/accepted单列；artifact_error不能被complete掩盖。
- [ ] 加恢复测试：37票先预算停止、下一次跳过已完成组并推进；partial journal可读但非complete cache；只重跑指定失败/partial票且保留全量其它票；代码/输入/模型/技能/协议变化失效旧复用。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_investigation_progress.py tests/platform/test_investigation_batches.py -q`确认失败。
- [ ] 实现组间原子进度、显式stopReason与计数、首组仓图复用；预算检查在新调用前，当前调用收尾超额如实记录。
- [ ] 保存initial/repair各次SDK账单及原始turns；确认累计/增量口径后才求和，无法确定时aggregate=unknown，不补0。失败组账单若SDK给出也必须保留，日志截断不影响主manifest。
- [ ] 同命令通过；验证进程中断恢复、坏cache不复用、已完成结果不被后续失败抹去；格式修复/收尾预算为0时不调用，停止原因准确且历史账单仍在。

### T4：Agent2实际只读工具路由

**Files:** Modify sdk/cartography.py `_make_options`/`_can_use_cartography_tool`、sdk/codegraph.py（必要时）；Test tests/platform/test_cartography_tool_permissions.py。

**Interfaces:** 保留允许工具/命令能力，限制必须在SDK实际执行前触发。优先PreToolUse hook，或SDK验证可达的收窄allow规则；不保留被whole-tool allow遮蔽的唯一检查。

- [ ] 写路由失败测试：允许的Read/Grep/CodeGraph与只读Bash可用；重定向写文件、shell串接写、命令替换写、任意Python写等实际执行前被拒；不能以callback单独返回deny证明成功。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_cartography_tool_permissions.py -q`确认当前遮蔽问题。
- [ ] 按已安装SDK的真实hook/权限API接入；版本不支持可靠限制时拒绝启用Bash或明确降级到只读工具，不静默放行。不改用户业务目录。
- [ ] 使用隔离目录和实际SDK适配路由/本地可控tool请求验证sentinel文件不被创建；模型API由桩替代。若SDK CLI不能在离线模式验证，标为待真实SDK gate，不将callback测试当通过；正式只读交付在验证前不放开Bash。
- [ ] 同命令通过，并记录SDK/CLI版本及路由证据；真实业务仓前后源码摘要在T10另验。

### T5：首轮与后续完整分析快照

**Files:** Create agents/analyst/analysis_store.py；Modify analyst/{attempt_store,run}.py、contracts/{repair,analysis_report}.py；Test tests/platform/test_analysis_snapshots.py。

**Interfaces:** save/load_analysis_snapshot按显式attempt定位；AttemptRecord保存analysisRef/digest，TicketReport保留同attempt/revision身份。

- [ ] 写失败测试：首轮即保存rootCause/claims/questions、候选顺序、ruledOut、方案和当前目标；二轮更新汇总后首轮仍完整；不同票/版本不可串用。
- [ ] 加原子性测试：快照/attempt/初始表任一写失败不覆盖旧latest；提交前中断目录不算完成；latest提交后汇总写失败可重建。同attempt同digest幂等、异digest拒绝覆盖；分析失败保存当前有效revision及具体错误，不能退回旧expected。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_analysis_snapshots.py -q`确认失败。
- [ ] 实现analysis→attempt→初始表→原子latest→派生汇总提交顺序（表渲染T6接入，T5先测提交前置文件钩子）；保存仓HEAD、dirty摘要/contentDigest、必要证据引用和实际模型/技能声明。复用现有锁，内部already_locked传递防嵌套锁；支持从快照重建报告。
- [ ] 同命令通过；检验首次report-only run_analyst也实际落盘，不只测试save helper。

### T6：产物内可填写反馈与内部导入

**Files:** Create agents/analyst/feedback_document.py；Modify analyst/{report,feedback,revisions}.py、cli.py、contracts/repair.py；Test tests/platform/test_feedback_documents.py。

**Interfaces:** render_feedback_form(snapshot)生成逐attempt表单并带展示绑定（不当安全保护）；parse_feedback_form返回内部Feedback；沿用feedback导入服务与InputRevision合并，增加questionAnswers/答案来源；表中baseRevisionId绑定原分析，内部parentRevisionId在锁内指向同父attempt最新反馈revision，二者不混用。

- [ ] 写失败测试：用户只填写答复区无需手写JSON；多问题答复/改预期/否定假设/附件可并存；空白不清空；主报告正文改动不被当用户事实。
- [ ] 加输入边界：旧表stale、错票/错attempt/digest、未知题号、修改题目/绑定、重复冲突、空表；规范化答复区摘要幂等，CRLF/LF与展示区改动不产生新反馈，有意义代码空白保留；仅改新答复时累计旧事实，同题更正保留历史但有效值只用最新答案。旧表报stale并指向新表，本期不做反馈分支。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_feedback_documents.py -q`确认失败。
- [ ] 实现逐attempt表生成、最新便捷链接与完整报告链接、文件格式识别及清晰错误输出；从不可变快照核对绑定/题目/摘要，不覆盖用户已填表；JSON只作为内部/自动化入口继续存在，用户不用维护它。
- [ ] 同命令通过；用实际CLI feedback导入生成后填写的Markdown，核对新revision和原表存档；同根锁保护检查→保存→指针更新，already_locked防嵌套。

### T7：首轮上下文与答案贯穿续跑

**Files:** Create agents/analyst/continuation.py；Modify sdk/{analyze,fix}.py、analyst/{run,context,sessions,revisions}.py、cli.py；Test tests/platform/test_previous_attempt_context.py。

**Interfaces:** build_previous_attempt消费显式父快照/反馈、当前WorkspaceSnapshot；AnalyzeRequest增加previous_attempt，FixRequest.analysis携带相同包。用户反馈kind/answers不再只有observed尾部文本。

- [ ] 写失败测试：resume/new/fallback均能在实际SDK prompt看到首轮outcome/候选/summary/ruledOut/方案/答案；丢SDK会话仍可继续；父快照缺失/损坏明确错误，不猜latest；必要答案/目标不可被摘要截断，SDK实际Read可读完整analysisRef，预算不足如实阻断不重问。
- [ ] 加变更测试：同HEAD不同dirty/contentDigest旧证据需重读；用户reject_hypothesis不沿用旧方案；expected变更仅使相关旧resolution失效，无关答案保留；部分应用/未知补丁不能按原基线盲重放。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_previous_attempt_context.py -q`确认失败。
- [ ] 加协议测试：缺evidenceRefs/引用不存在/坏问题结构保留原文诊断，一次格式修复只引用现场证据；仍失败记工程分析失败，不造choice或证据。
- [ ] 实现受控摘要+analysisRef按需读取；明确当前目标优先，不无限复制全部历史消息。复用classify_patch_state与现补丁关联，不建第二套PatchSet逻辑。
- [ ] 同命令通过；正式resume CLI→run_analyst→SDK adapter→新报告链验证，不能只assert dataclass存在字段。

### T8：问题事权与有界收敛

**Files:** Modify analyst/continuation.py、{claims,evidence,run,report}.py、sdk/analyze.py、sdk/skill_inject.py的规则附录、contracts/repair.py；Test tests/platform/test_question_convergence.py。

**Interfaces:** consume_question_answers输出QuestionResolution/剩余阻断/违规；既有validate_edit_decision仍检查目标、当前代码证据、来源与授权。

- [ ] 写失败测试：明确用户业务答案消费后resolved；无答案且无唯一业务规范的产品choice不能由模型自行resolved；普通实现选择有具体决策/依据后不单独阻断，不能仅改category放行；真正产品冲突/关键事实缺口仍阻断。
- [ ] 加状态测试：答非所问标insufficient；resolved问题无新依据重开被拒；重开引用当前新证据或具体答案矛盾，保留旧记录。父账本旧题必须保留或有resolution，模型漏题不能消除门槛；改写旧题却缺predecessor映射为协议缺口；真正新题可无前题，但需明确首次发现的阻断依据。触发一次收尾而非无限问用户。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_question_convergence.py -q`确认失败。
- [ ] 写入技术事权默认策略、目标优先级和答案消费收尾；同会话最多2-turn且不重置剩余预算；收尾成功直接进入原fix loop，失败/无额度标分析不完整。读过代码/有引用不能自动解决语义冲突，也不因“第2轮”强行开编辑。
- [ ] 同命令通过；断言剩余未解决题仅verification/follow_up时可继续检查既有编辑门槛，已resolved的blocking/choice不再阻断，决定根因方向的缺口不能靠误标verification被默认放行。语义分类实际正确性移交T10，不用fake证明模型能力。

### T9：正式入口端到端和原有修复门槛

**Files:** Modify cli.py、workflow/{graph,run,state}.py、http/{models,runner}.py、agents/cartographer/run.py、agents/analyst/run.py；Create tests/integration/test_handoff_feedback_convergence.py；Extend现HTTP/repair_entry/patch/checks测试。

**Interfaces:** out-dir/artifact_dir（未指定时按T3默认）为A2和A3提供同一持久化根及完整批次/知识/报告；显式resume_dir/ticket_ids通过CLI/应用服务传递。HTTP只接既有run参数/选项；不新增反馈页面或隐式二次执行。A2/A3及汇总引用同一batch/attempt身份。

- [ ] 写端到端失败测试：A1输入→真实SDK适配返回混合坏字段→A2合法线索保留→A3首轮快照/反馈表→用户填写→实际feedback CLI→resume后SDK prompt携previousAttempt与答案。
- [ ] 隔离小仓放一个真实可验证缺陷（如明确参数顺序错误）：资料/目标已明确，受控模型边界指示正确源码修改；`--apply-fix`确实走现有fix loop、产git apply可应用补丁并跑真实断言。该测试只证明控制链及补丁验证，不证明真实模型会正确作答。
- [ ] 对同流程`--execute`断言编辑器零调用、业务文件前后摘要相等；HTTP显式false不得被环境true覆盖；不再引入内部TypeError删参数重试。
- [ ] 运行`py -3.12 -m pytest tests/integration/test_handoff_feedback_convergence.py -q`确认新增行为缺失。
- [ ] 实现参数/工件贯通及逐票异常隔离；当前final PatchSet验证汇总、语义复核failed/未执行、旧补丁applied/partial/unknown、源码漂移各门槛保持。
- [ ] 同命令与相关回归通过，再执行`py -3.12 -m pytest tests -q --tb=short -rs`；按新失败修复/复跑，不把材料依赖skip算通过。CodeGraph可用性单列，不全局禁用掩盖失败。
- [ ] 增加并发/恢复集成测试：导入对导入、导入对resume、两次resume同根只能一个写者；多次导入后续跑累计全部答案且绑定原父attempt；另票结果不丢，汇总损坏可从已提交latest及快照重建；遗留锁不按任意超时强抢。
- [ ] 人工核对产物文件可读/历史不被覆盖/日志引用仍在；没有真实SDK smoke时不得把只读工具执行gate写通过。

### T10：效果计分、模板与真实项目验收

**Files:** Modify packaging/eval_agent3.py、docs/field-eval/agent3/{README.md,templates/ticket-review.md,templates/ticket-review-summary.csv,templates/batch-evaluation-report.md}；Create tests/platform/test_convergence_metrics.py；执行时在reviews/新建实际试点记录。

**Interfaces:** 评分case绑定当前product/defect/attempt/reportDigest；增加人工eligibility及理由/标注时间、有效答案与本轮必答题分母、反馈是否足量、尝试/可应用候选/验收结果、问题消费/重开、耗时与成本。未知/pending独立统计，不默认为成功或凭空造真值。

- [ ] 写指标失败测试：固定样本20票，14实际成功、3已知失败、3pending时，固定分母保守值=14/20、已验收观察值=14/17；pending不是已证失败。不能删3票后声称固定分母成功率提高。报告模式修复率null；重复attempt不重复计同一缺陷；stale评分不继承；答案消费/重复必答题按方案分母计算且零分母null。
- [ ] 运行`py -3.12 -m pytest tests/platform/test_convergence_metrics.py -q`确认失败。
- [ ] 实现分别统计全部票/独立可修票、答案消费/修复尝试/候选可用/实际验收、重复提问/重开理由和成本；模板注明70%为待业务确认提议，无已确认SLA不自动宣告业务通过。
- [ ] 同命令通过并完善评测材料字段。先冻结8—12票验证真实SDK输出/权限/答案消费，再扩至少20独立可修票；业务资料未齐写“未执行”，不能用合成20票计分测试冒充真实70%。
- [ ] 在固定模型/HEAD/技能/预算条件下人工核对每票目标、因果、修复及回归；二轮有足量答案却仍不修时必须归因，不能只归“产品没决策”。用户拒绝/环境缺失/pending完整记录。

## 交付检查表

- [ ] E1：T0—T4通过。A2局部故障不静默丢成果，SDK工具执行边界有证据，进度/账单可追。
- [ ] E2：T5—T9通过。首次报告可填写、任意会话可续接、答案已消费、隔离fixture确实修复且原回归不退化。
- [ ] E3：T10工程计分/模板通过。空样本、stale、pending、重复计数、分母变更均不虚报成功。
- [ ] S：真实SDK smoke通过。记录模型/SDK/CLI、输入模态、工具路由、解析和保全；若缺凭据/CLI条件，明确未通过而非“默认具备”。
- [ ] B：真实项目评审通过。独立标注、固定分母、真实验收与成本可复算；70%目标是否采用需业务确认，不能由工程测试自动满足。

分别记录 E（工程）、S（真实 SDK）和 B（业务）验收结果。当前状态见[当前实现与验收状态](../../architecture.md#验收状态)。

## 文档自查

需求覆盖：A2重复丢结果=T1/T2；误complete/恢复=T3；只读执行=T4；用户免手写JSON=T5/T6；previousAttempt=T7；choice事权与答案收敛=T8；正式入口与实际编辑=T9；工程/真实效果分离=T10。五类Review Focus均有任务归属。T5只定义提交顺序及前置文件检查，T6提供真实表渲染，T9验全链，避免T5反向依赖T6。schema共用版本更新不等于本轮重写Agent1筛选策略。

## 2026-11-17复审后的新增验收场景

以下属于既有任务的补充，不新增平台或任务层：

| 场景 | 必须观察到的结果 | 归属 |
|---|---|---|
| 一组8票中1票重复、1票坏facts、1条组外ID | 无歧义合法票调查仍在；重复票单独隔离；坏facts不带走其合法候选 | T2/T9 |
| 顶层modules坏、末尾输出无关JSON、收尾漏掉前轮合法票 | 合法调查不退baseline；全部输入及字段rawRef可读 | T1/T2 |
| SDK异常/磁盘失败/最终生产契约失败 | 故障显式，收到并成功保存的accepted内容可恢复；离线重放零SDK调用 | T1/T2/T3 |
| 模型二轮不再列首轮未解choice | 父账本仍阻断，不因遗漏变成allowed | T8 |
| 用户回答产品目标，模型又把同题变成实现选项 | 有界处理后产生具体方案；足证且授权则正式fix loop尝试；真实语义另做人工验收 | T8/T9/T10 |
| 用户修正expected、同时补多题 | 相关旧决定显式失效，无关已答题保留，prompt完整承载 | T7/T8 |
| 旧表改metadata/两进程同时导入/用户已填文件 | 真源校验/锁拒绝冲突，不串票、不覆盖填写内容 | T5/T6/T9 |
| 格式修复与决策收尾均触发但总预算为零 | 不产生额外调用，不把预算失败包装成用户choice | T3/T8/T9 |

工程验收不要求模型任意语义零错误，也不以“二轮必须有补丁”强迫错修；要求控制链、隔离与授权行为可重复验证。真实项目验收仍单列S/B，首批无实际反馈数据不能写成“已证二轮可修”。

### 本轮证据到新增回归的映射

- 三项目93票/85次invalid_match与本地字符串facts复现 → T1/T2/T3；只有字符串复现可作确定输入，85次具体坏字段仍未知，补充合成坏字段覆盖但不伪称实测原文。
- `sdk/cartography.py`现有`_merge_enrichment`整组身份raise、`validate_code_knowledge`异常整段fallback、`_parse_session_json`首个JSON优先 → T2的邻票隔离、最终组装、多候选信封回归。
- transport的0935/2247工程分析失败 → T7/T9检查缺引用/解析失败的明确分类与有界修复；不声称两票都已证实由同一坏字段导致。
- 18票全allowed=false、41个问题及已有目标冲突案例 → T8/T10的事权和反馈试点；它们只证明首轮有阻断，不证明用户回答后仍重复阻断。
- 当前`save_attempt`直接写latest、`import_feedback`未持同根锁、`run_analyst`按latest取父轮 → T5/T6/T7/T9的原子提交、累计revision、显式父attempt与并发回归。
