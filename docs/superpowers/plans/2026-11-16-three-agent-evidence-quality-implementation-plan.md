# 三Agent真实项目证据质量优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日期：2026-11-16。修订：同日完整复审。状态：用户授权后已实施；Q0—Q8工程完成，Q9离线入口完成、真实模型/业务复评待验。见[当前实现与验收状态](../../architecture.md#验收状态)。

**Goal:** 让原文、逐票调查与用户目标可信传递，报告明确区分事实、假设和验证待项。

**Architecture:** 增量修改现有契约和SDK prompt，复用三Agent编排、逐票存储和正式入口。新增原文质量、分组调查、完整revision合并三个小模块，不新增agent或数据库。

**Tech Stack:** 现有Python >=3.11 / Pydantic / LangGraph / Claude Agent SDK / pytest。

**Spec:** [完整优化方案](../specs/2026-11-16-three-agent-evidence-quality-design.md)。证据：[实测复评及用户边界](../../field-eval/agent3/reviews/2026-11-16-three-agent-real-project-assessment.md)、[24票表](../../field-eval/agent3/reviews/2026-11-16-ticket-reassessment.csv)、[交付包](../../../runs-2026-11-16/bugfix-runs-2026-11-16-交付包.zip)。前置：[11-15计划](2026-11-15-agent3-repair-feedback-implementation-plan.md)。

## Global Constraints

- 本次只出报告是明确要求，无补丁不判失败；applyFix=false全链路不可调用编辑器。
- 约256K非多模态是本次配置；下一轮偏好约1M多模态，记录实际能力，不设通用1M硬门槛。
- 没有旧契约兼容要求；升级版本并同步输入、prompt、解析、样本和调用方，不能静默丢新字段。
- 摘要匹配、代码片段存在、boundSkills不是独立的因果或执行证明。
- 优先原文与目标正确、调查覆盖真实；不新增数据库、多agent投票、分布式系统。
- 修改前登记当前HEAD与dirty。只提交明确授权的任务文件，不重置用户改动。本计划本身不安排自动提交。
- 运行证据包只读，不执行其中脚本/pickle；回归夹具保留必要脱敏片段与来源摘要，不复制整批业务数据进tests。

## Review Focus

1. source字段非空但用例预期与现象矛盾：原文应保留、冲突应暴露（Q1/Q2）。
2. 用户已确认移除开关，但模型发现弹窗风险：目标不能被另一个问题替换（Q3/Q5）。
3. 有验证待项但修法明确：不因任意开放问题永久拒绝（Q4）。
4. 第17张或中途失败的一组：必须有可续跑且真实的覆盖状态（Q6）。
5. 评语引用旧主张或图像配置不支持：不能误算根因/预算失败（Q7/Q8/Q9）。

## 优先级与依赖

| 任务 | 优先级 | 依赖 | 独立可验收产物 |
|---|---|---|---|
| Q0 固定证据与现状 | P0 | 无 | 数据清单与最小夹具 |
| Q1 原文保全 | P0 | Q0 | 可追溯原始票面 |
| Q2 质量和筛选 | P0 | Q1 | 冲突/缺口标签，不误拒具体缺陷 |
| Q3 完整反馈与目标 | P0 | Q1 | 不丢字段、不改变用户目标 |
| Q4 问题分类与行动资格 | P0 | Q0（类型骨架）；Q3正式集成 | 阻断/验收/后续分离 |
| Q5 因果声明与报告 | P0 | Q0（类型骨架）；Q2,Q4正式集成 | 逐主张证据与条件性总结 |
| Q6 Agent2分组调查 | P1 | Q0,Q1；Q5联合验收 | 全量覆盖清单与可续批调查 |
| Q7 技能和模型manifest | P1 | Q0 | 可解释加载/模态行为 |
| Q8 评测绑定和评分修正 | P0 | Q0；集成Q5 | 与实际报告一致的评分 |
| Q9 正式入口与实项目对照 | P0验收 | Q1—Q8 | 工程与报告效果分开验收 |

Q1/Q2与Q3/Q4分为Agent1、Agent3工作包；Q6是Agent2工作包；Q7/Q8是支撑包。契约先串行定稿，共享run.py/prompt变更串行集成。P1也是本次方案交付范围，不是永久可选项；Q8可先做数据一致性修正，不必等所有功能。Q0先一次定稿Claim/Question/Investigation的最小类型与统一版本清单；Q4不依赖Q5实现，Q6也不必等待Agent3全部完成。类型骨架不算生产能力完成。

## 文件与接口约定

表内缩写：`contracts/`=contracts/bugfix_contracts/；`a1/`=agent1/bugfix_agent1/；`platform/`=platform/bugfix_platform/。新增嵌套类型统一放repair.py及所属输入/知识契约，不每个类型一个模块。测试路径均相对仓根。

阶段中允许契约先更新、生产入口随后接入，但不能把仅有类型/测试函数的状态标为任务全部完成。每项“正式入口”必须沿现有CLI/应用服务实际调用，不只调用helper。

## Q0：冻结证据与基线

**文件范围：** 新增 tests/fixtures/repair_quality/manifest.json；tests/platform/test_quality_evidence.py；contracts/{repair.py,analysis_report.py,code_knowledge.py,defect_batch.py,common.py}的共享类型骨架。

**接口/交付：** manifest保存包SHA256、条目ID、report摘要和用途；共享类型先固定字段、引用与schema升级清单，具体行为后续任务实现。

- [x] 登记基线并制作最小夹具，人工核对LED旧产物、93新输入、24选样和模态400来源；这些是取样账本，不为固定数字编写无生产行为的镜像测试。
- [x] 为共享类型写JSON往返、错误版本和引用结构测试，不能把临时schema未接入口当已交付。
- [ ] 运行 `python -m pytest tests/platform/test_quality_evidence.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：从现有统计与24票表选最小脱敏夹具，列清作者复核记录与本次可直接核实的字段；登记主分支HEAD、dirty和基线测试。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q1：保全原始票面与来源

**文件范围：** contracts/defect_batch.py；a1/ingest/{field_map.py,csv_source.py,xlsx_source.py}；a1/defect_batch/{distill.py,cluster.py}；新增a1/defect_batch/source_quality.py；platform/agents/analyst/context.py；platform/sdk/{analyze.py,cartography.py}的原文按需访问入口；tests/agent1/test_source_document.py。

**接口/交付：** SourceDocument、SourceSection；build_source_document(raw: RawDefect) -> SourceDocument。

- [x] 写行为回归，断言：04188前置/测试数据/问题回放链接可回查；文本特殊符号及空白不丢；独立CSV列测试环境/版本/型号能跨ingest→batch→context保留；附件未知不伪装已读；中文offset与UTF8哈希可复算；JSON往返保真。
- [ ] 运行 `python -m pytest tests/agent1/test_source_document.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：保存全文/源记录/哈希和sourceSections位置；下游按需展开而不强制全量注入；同步schema版本、fixtures、样本及导出；两个SDK prompt/可读取产物必须实际可访问sourceDocument，不能只给TaskContext新增字段却不传模型。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q2：区分质量冲突与调查资格

**文件范围：** a1/defect_batch/{source_quality.py,expect_quality.py,rules.py,screen.py,review.py}；contracts/defect_batch.py；tests/agent1/test_input_quality.py。

**接口/交付：** assess_input_quality(source: SourceDocument, observed: str, expected: str) -> InputQuality。

- [x] 写行为回归，断言：04188/03610错配不当可靠验收；03691无提示有可调查标签；11009071明确排行对比不因模糊词硬挡；不将所有needs_info强升strict。
- [ ] 运行 `python -m pytest tests/agent1/test_input_quality.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：增加origin/relevance/issues；规则标明显关系，语义未知保留uncertain；已有语义审阅负责复杂冲突，不新加每票调用；修C1c/C1e，保留明确排除。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q3：完整合并反馈并保持目标

**文件范围：** contracts/repair.py；新增platform/agents/analyst/revisions.py；platform/agents/analyst/{feedback.py,context.py,run.py}；platform/cli.py；platform/http/{models.py,runner.py}；platform/sdk/analyze.py；tests/platform/test_revision_targets.py。

**接口/交付：** merge_revision(parent: InputRevision, feedback: Feedback) -> InputRevision；feedback.kind与clearFields/removeAttachmentIds；parentRevisionId与parentAttemptId分开。

- [x] 写行为回归，断言：工程层验证09314明确expected及原始补充穿过feedback→revision→SDK prompt→报告；实际模型是否坚持移除目标在Q9逐主张评审，不用fake返回正确方案冒充通过；未知kind不丢expected/steps；显式清空与未提供不同；验收反馈不无意变更预期；父版本错误与同ID不同内容明确冲突；连续补充不丢第一轮事实；CLI resume --execute实际调用run_analyst(apply_fix=False)、零fix调用且保存新报告。
- [ ] 运行 `python -m pytest tests/platform/test_revision_targets.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：保存完整父票面与变更来源；显式expected优先；unknown纯文本保留且展示，不凭字段名把目标当observed；prompt包含当前目标/变化/原因猜测；新增resume --execute执行报告模式续跑，纯预览保持无执行，--apply-fix仍需显式开启。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q4：问题分类和门槛

**文件范围：** contracts/{repair.py,analysis_report.py}；platform/agents/analyst/{evidence.py,run.py,report.py}；platform/sdk/analyze.py；tests/platform/test_question_gate.py。

**接口/交付：** Question(id,kind,relatedClaimIds可选,reason,requestedEvidence)；validate_edit_decision保持现签名。

- [x] 写行为回归，断言：文案顺便同步follow_up不阻当前修复；设备是否置红blocking继续阻断；无实机verification可生成建议；旧外部版本明确拒绝，新版本模型漏结构有界修复后仍无结果记incomplete；缺relatedClaimIds的blocking不能放行；applyFix=false编辑runner调用次数=0。
- [ ] 运行 `python -m pytest tests/platform/test_question_gate.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：改为结构化questions；旧openQuestions从结构派生；按单票目标的blocking/choice阻断，不做子补丁授权；报告模式显示行动资格但不编辑。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q5：因果主张与最终报告一致

**文件范围：** contracts/{repair.py,analysis_report.py}；platform/sdk/analyze.py；platform/agents/analyst/{context.py,run.py,report.py}；tests/platform/test_claim_report.py。

**接口/交付：** Claim(claimId,statement,role,status,evidenceRefs,assumptions)；TaskContext携带currentTarget和claims。

- [x] 写行为回归，断言：程序层断言：无工具观测的返回不得标observed，缺证据引用/矛盾状态需报输出不完整，源码片段匹配不自动改变Claim.status，真实JSON解析字段不丢；确定静态参数传反仍可supported。模型对LED04084/peitao02007/hcp04762的实际语义质量另行人工评审，不能fake预设conditional就宣称识别正确。
- [ ] 运行 `python -m pytest tests/platform/test_claim_report.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：prompt收尾区分事实/假设/附带风险，保留关键原文位置；片段校验只确认引用；摘要与claim状态一致；未完成仍保存已确认事实和具体下一步。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q6：Agent2小批续跑与调查交接

**文件范围：** contracts/code_knowledge.py；新增platform/agents/cartographer/investigation.py；platform/agents/cartographer/run.py；platform/sdk/cartography.py；platform/agents/analyst/context.py；tests/platform/test_investigation_batches.py。

**接口/交付：** plan_groups(ticket_ids: list[str], group_size: int = 8) -> list[list[str]]；Investigation包含facts/scopes/ruledOut/questions/nextChecks。

- [x] 写行为回归，断言：37票无16票后静默假完成；预算不足明确未调查；failed组可单独重跑；零候选但有搜索记录不当失败；A3接到未调查状态自行核实；费用区分仓级/组级；模型返回组外票拒绝合并；重复执行同键不重跑已完成组，代码/输入/技能变化不得复用；预算不足不启动新组，收尾超额如实记录。
- [ ] 运行 `python -m pytest tests/platform/test_investigation_batches.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：拆分既有仓图生成与逐票prompt，仓图同快照一次；顺序循环各组SDK显式ticket范围/预算，不新建后台调度器；总预算耗尽停止；组失败不抹已完成结果；续跑按选择范围；修prompt允许有限调用链，token-hit只是locator。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q7：技能与模型配置可观察

**文件范围：** platform/sdk/{skill_inject.py,analyze.py,cartography.py}；platform/http/models.py；platform/cli.py；新增platform/sdk/runtime_profile.py；tests/platform/test_runtime_profile.py。

**接口/交付：** RuntimeProfile(modelId,contextWindow,inputModalities,capabilityStatus,budgets)；SkillDiscoveryResult发现/拒绝原因。

- [x] 写行为回归，断言：hcp未选技能有原因；选中无profile技能正文可读但不伪装applied；文本模型任务仍可用；图像400不标max_turns；1M声明不自动标verified；无凭据smoke如实未执行；实际输入图像未读取不能因声明multimodal写read=true。
- [ ] 运行 `python -m pytest tests/platform/test_runtime_profile.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：显式技能目录/allowlist支持无profile技能，默认不全量装；按仓作用域发现；运行manifest记录声明或已验证能力；可选smoke；不支持图像明确降级/配置错误，不无限同请求重试。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q8：评测绑定实际主张

**文件范围：** packaging/eval_agent3.py；docs/field-eval/agent3/{README.md,templates/}；tests/platform/test_eval_agent3.py；新增tests/platform/test_claim_ratings.py。

**接口/交付：** RatingBinding(product,defectId,attemptId,reportDigest,claimIds可选)；score_report新增declared alternatives口径。

- [x] 写行为回归，断言：交通06318旧评语不套新主张；LED01340正确归模态配置；保留本包复算账本17/24与18/24；生产单测使用小型多前缀案例验证算法，不加载全业务包、也不把目录命中当根因率；缺attempt用报告摘要且标级别；空样本不通过。
- [ ] 运行 `python -m pytest tests/platform/test_eval_agent3.py tests/platform/test_claim_ratings.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [x] 实现：主前缀与含Alt分开输出；评语版本不符stale；执行完成率、诚实性和根因证据分开；保留原始分母/缺失项；更新模板。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。

## Q9：入口集成和固定样本对照

**文件范围：** 新增tests/integration/test_quality_report_flow.py；docs/field-eval/agent3/reviews/下新增实际运行记录（执行时日期）。

**接口/交付：** run_analyst与feedback/resume CLI复用上述接口；无额外调度服务。

- [x] 写行为回归，断言：报告模式零代码变更；完整原文/目标/未决问题可追溯；失败票仍报告；报告模式CLI续跑实际再分析且零编辑；补丁模式门槛用隔离夹具维持回归；真实模型未执行不冒充通过；业务评审人与证据位置明确。
- [ ] 运行 `python -m pytest tests/integration/test_quality_report_flow.py -q`，确认新增测试因缺少目标行为失败；已有环境失败单独归因。
- [ ] 实现：贯穿原始输入→A1→A2→A3报告→补充→新报告；保存每阶段原始产物和真实工具证据；约1M多模态运行单列，固定条件分两次比较。
- [x] 同命令复跑，新增与相关回归全部通过；核对正式入口调用，不能只验类型存在。
- [x] 自审改动范围、更新样本和任务证据；未获授权不自动提交/推送。


## 里程碑与完成门槛

- [x] M1（Q0—Q5）：一张冲突票及一张补充目标票穿过正式报告入口，资料保真、目标一致、问题分类正确，零编辑调用。可先交付内部试用，不叫三Agent整体完成。
- [x] M2（Q6—Q8）：37票模拟组调度、显式技能读取、评语过期检测均通过；按预算停止的剩余票有真实状态。
- [ ] M3（Q9）：正式CLI/应用入口贯穿，报告及后续反馈完整；固定8—12票业务复评。工程测试通过与业务分析正确性分别汇报。

执行前在项目专用Python环境验证依赖与SDK版本，不假定系统python有pytest。Windows现有可用环境可用 `py -3.12 -m pytest ...`；命令中的python指同一已验证解释器。真实SDK smoke需要已有凭据，缺少时不阻塞离线开发，但M3模型链路明确未验。

集成检查：`python -m pytest tests/contracts tests/agent1 tests/platform tests/integration -q`。CodeGraph可用性由测试环境显式配置并记录，不把跳过项算通过；必要时单独验证该后端。运行次数仅在新变更/失败需要时增加。

## 实项目对照协议

1. 选8—12票并冻结原始票、业务HEAD/dirty、Agent版本、skill及预算，参考方案第8节案例。
2. 保留本次256K文本运行作为历史基线；先在独立checkout的原版本上换约1M多模态模型，记录模型/图像能力变化；其后在相同新模型配置下比较优化版本。预算不一致明确列出，不宣称单变量因果。
3. 全程applyFix=false，记录原文遗漏、事实错误、过度因果断言、目标遵守、合理阻断/可行动建议、调查重复时间与成本；不统计补丁成功率。
4. 图像票有可读取截图才可评图像理解；读到图片不等于根因已证实。设备行为仍需真实日志。
5. 人工评分绑定版本和主张；陈旧评语重做，不自动继承。若业务资料不足，填无法判断，不凑通过率。
6. 业务阶段材料尚未齐时交付工程结果和待验清单，不能宣称整体业务效果提高。补丁模式另设后续验收，不作为本次用户只出报告要求的反向扣分。

## 自查与不实施声明

设计覆盖：Agent1=Q1/Q2，Agent2=Q6，Agent3目标/门槛/因果=Q3/Q4/Q5，模型与技能=Q7，评测可信度=Q8，正式入口=Q9。Review Focus五项分别有明确测试归属。本节为原计划的范围说明；执行状态以各任务工程复选框和执行自查为准。真实模型与业务验收保持未完成。字段名和groupSize为推荐实现选择，可在不改变业务语义的前提下细化；改变目标优先级或报告模式授权范围需同步修订设计。

## 验收证据分层与实际执行顺序（完整复审补充）

- 工程层：规则/解析/字段继承/门槛/分组/错误分流使用真实控制链和注入runner；fake只验证调度和边界，不证明模型理解了业务。
- SDK层：使用真实SDK适配器，mock供应商返回验证schema/图像错误处理；真实模型smoke验证输出、图片和skill实际读取。缺任何条件明确未执行。
- 业务语义层：人工逐主张核对目标、支持证据和剩余歧义。最低两个评审方向均覆盖：该阻断时不乱给确定结论、证据充分时不永久拒绝。不为“排版美观”或字段齐全评分为成功。
- 依赖执行顺序建议：Q0类型/账本→Q1→Q2；Q3→Q4→Q5并行准备后串行集成；Q6/Q7/Q8可在共享类型稳定后独立推进；Q9先跑最小正式入口，随后集成全部能力。模型重测不阻塞代码开发，代码功能完整不等于实项目语义验收通过。
- 契约集成清单：contracts/__init__.py、公共版本常量、Agent1导出、Agent2和Agent3请求/响应prompt、parse/merge、workflow gates、CLI/HTTP序列化、报告模板与样本一并更新。旧归档仅作为历史证据读取，不通过新生产契约回放；需旧版本重跑时用隔离checkout，不开发历史兼容层。

本轮复审修正：报告模式resume缺执行路径、独立CSV业务字段遗漏、Claim/Question定义顺序、分组复用与预算边界、revision父链、将语义期望硬写成单测的验收问题。只更新文档，没有运行未来产品测试。

独立设计复审（2026-11-16）：修订后未发现必须修改的重大依赖矛盾或明显过度设计。已再次核对10项任务、所有本地链接和未完成标记；没有运行产品测试。

## 实施收尾（2026-11-16）

已完成Q0—Q8工程工作及Q9 离线正式入口。该轮生产契约为 0.3.0，当前已升级至 0.4.0；报告模式零编辑、完整反馈继承、分组预算/缓存、claims/questions及评分绑定已进入生产控制链。

原计划中“先观察每项新测试因缺实现失败”的流程复选框未追认全部执行；不能事后把夹具错误当每项都严格完成red-first的证明。已实际运行新增行为回归及完整测试。Q9中真实工具轨迹、约1M多模态模型及固定8—12票业务对照仍未执行，M3整体不勾通过。未提交或推送代码。

## 2026-11-17 实现完整复审

实施收尾补齐了正式HTTP/工作流授权传递、SDK合并前身份校验、双SDK读取轨迹、附件门槛同步、失败票目标及旧报告版本校验等遗漏；不新增架构。工程验证与真实模型/业务待验继续分列。
