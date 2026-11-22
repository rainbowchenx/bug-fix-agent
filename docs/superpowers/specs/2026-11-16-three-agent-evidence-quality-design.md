# 三Agent真实项目输入、调查与报告质量优化方案

日期：2026-11-16。修订：同日完整复审。状态：工程实现及离线验收完成；真实模型及业务复评待验，见[当前实现与验收状态](../../architecture.md#验收状态)。用户已明确不做旧兼容、以效果为准。

依据：[四产品线复评及用户补充](../../field-eval/agent3/reviews/2026-11-16-three-agent-real-project-assessment.md)、[24票复评](../../field-eval/agent3/reviews/2026-11-16-ticket-reassessment.csv)、[统计](../../field-eval/agent3/reviews/2026-11-16-artifact-statistics.json)、[本次交付包](../../../runs-2026-11-16/bugfix-runs-2026-11-16-交付包.zip)。前置架构：[11-15方案](2026-11-15-agent3-repair-feedback-design.md)与[实施计划](../plans/2026-11-15-agent3-repair-feedback-implementation-plan.md)。本稿针对实测暴露的问题增补和修正，不重写已实现的工作区/补丁闭环。

## 1. 范围与目标

本次256K非多模态模型是运行配置选择；图像400不计作Agent3分析错误。只出报告是用户要求，不以无补丁扣分。下一轮偏好约1M多模态模型，重跑记录真实模型、服务能力和生效预算，不推定大窗口自动改善效果。

优化目标：资料能回查、目标不漂移、调查覆盖真实、因果表达与证据一致、完整报告能推动下一步。维持Agent1准备资料、Agent2逐票前置调查、Agent3核实并承担最终分析/修复责任。报告模式与补丁模式继续共用证据，不强制每票确定根因。

本期不新增agent、数据库、分布式调度或统一业务测试平台。不要求上传完整业务仓。样本JSON/片段可支持离线机制验证，真实语义收益仍需业务人员确认。

## 2. 证据索引与问题对应

交付包内路径统一从`_deliverable/`起算；相同ID须同时绑定产品和attempt。不存在attempt文件时使用报告摘要与条目ID定位。

| 证据 | 本批事实 | 设计响应 |
|---|---|---|
| peitao/00…CSV与BGCM2026110304188 | 用户管理卡等待，步骤却来自键盘退出；有回放线索未传递 | 原文保全、冲突标注 |
| hcp/00…与03610 | ONVIF跳转对应ISUP步骤预期 | 预期来源与语义相关性分开 |
| hcp完整batch 03691/11009071 | 无错误提示、排行相反仍被缺信息规则拦截 | 缺口不等于禁止调查 |
| 三份新code-knowledge | 93票中45未调查，单次最多16票 | 小批续跑、准确覆盖 |
| hcp04123/04635、peitao02007 | 同类词面候选，Agent3仍能重查 | 候选与事实分开，保留前置调查 |
| peitao09314/05 | 用户确认移除开关，二轮转去修弹窗 | 用户目标与原因猜测分开 |
| LED04084、peitao02007 | 设备置红、2s因果未证实却写确定总结 | 因果链前提与确定性一致 |
| 24份03 | 全有openQuestions，全部allowed=false | 区分关键阻断、跟进与验收项 |
| LED01340 JSON | 模型不支持图像400 | 配置修正及能力可观察性 |
| transport06318、hcp03220、LED04084的03/04 | 人工评语对应旧机制 | 评分绑定产物版本/主张 |

## 3. Agent1：完整原文加轻量质量层

### 数据与职责

在BatchTicket增加`sourceDocument`：内含原始description全文、字段名/源记录ID、内容SHA256；首期直接内嵌，按需展示，不依赖外部文件才能恢复。同时保留原始行的业务字段（如测试环境、产品版本、型号、出现概率），不能只保全description而遗失独立CSV列。将来源适配器的原始业务列映射传至SourceDocument.fields，不把人员隐私字段默认展开到模型上下文。全文以原始Unicode文本保存；段落offset以Unicode码点计、区间左闭右开，SHA256计算原始文本UTF-8字节，不先压平空白。

另保留`sourceSections`（前置条件、测试数据、问题/定位备注、附件描述）及每段在原文中的位置。既有observed/expected/steps作为提炼视图，source三字段不再宣称完整原文。

附件引用记录原始URL/文字、可用性unknown/available/unavailable、是否实际读取；不能将有链接视为读过图片。无需Agent1自动登录所有回放系统或下载视频。

新增`inputQuality`：expectedOrigin（explicit/inferred/absent）、expectedRelevance（consistent/conflicting/uncertain）、issues（类型、原文定位、说明）。Agent1规则只指出明显问题；需要语义判断的uncertain交给已有审阅阶段或Agent3，不另加每票模型调用。未检测到冲突不等于业务保证一致。首期不开发通用中文语义矛盾检测器：规则只能确定格式/空白/明显模板情况；复杂相关性由现有Agent1审阅或Agent3本次分析判断。不能通过硬编码04188/03610工单号使测试通过。

### 筛选策略

明确用户/政策排除继续保留；描述质量规则只产生缺口标签。C1e“没有错误提示”与“只写发生错误”区分；C1c识别明确比较对象/方向，如排序相反。needs_info允许有限调查，不自动升为strict；由Agent3判断信息是否足够。不得为增加严格池数量而把未知预期改成明确预期。

## 4. Agent2：分组可续跑的逐票调查

采用现有顺序执行，不引入后台调度器。仓级知识在代码/规范快照一致的同一运行内只生成一次；换版本或配置变化再刷新。新增调度器将目标票按稳定顺序分组，初始groupSize=8（可配置且不超过现有16票的单次上限）；每组共享仓级导航，独立SDK调查和预算。设置整批总预算，组级独立失败；到上限的剩余票标not_investigated，不能自动无限续跑。重复运行只处理明确选择的未调查/待刷新票。续跑键至少包含票输入摘要、仓库快照、模型/技能配置摘要；已完成结果仅在键一致时复用。模型返回组外ID拒绝合并，同票重复结果保留阶段来源，不覆盖其它组事实。当前调用在预算到期后可能有收尾成本，区分模型API硬上限和应用软上限；每组启动前检查剩余预算，记录实际成本与超额，不能宣称平台可精确预测费用。共享建图与组级调查提示词分离，避免每组重复跑完整仓图。

每票输出`investigation`：status、facts（引用位置/片段/版本）、hypotheses、searchedScopes、ruledOut、openQuestions、nextChecks。complete定义为“本轮约定的前置调查已返回并有可核实事实/已查范围”，不意味着根因确定；必须记录来源为tool_observed或model_reported，模型自述搜索范围不能伪装成独立工具轨迹。零候选但有明确搜索范围也可完成本轮调查，不能靠候选非空决定。

path-token命中只记locator，不变成code fact。模型可沿最强线索有限追调用链；删除一刀切禁止逐票follow imports/callers的限制，使用预算控制深度。先建立中文业务对象与实际入口关系，再决定是否深入。不可用通用loading或data候选填满配额。

Agent3接收整个investigation，优先核实事实、避免重查已排除范围；仍允许推翻、独立重查。没有调查的票由Agent3明确自查，不承诺上游已读。成本分别记录仓级、各组、salvage和逐票可归属部分，避免拿全批费用除以6票误比。

## 5. 技能与模型运行配置

业务技能采用显式运行目录/allowlist优先；仓内未标profile的技能不静默消失，列出eligible/rejected及原因。默认不无差别加载全部个人/仓内技能；选中无profile的技能可以由运行配置明确作用于cartography/analyze。多仓按repoId作用域，不仅扫描容器根目录。记录selected/read/applied和输出依据。

运行manifest增加modelId、声明contextWindow、inputModalities、实际maxTurns/maxTokens及capabilityStatus（declared/verified/unknown）。能力来自运行配置与可选低成本smoke，不发明自动探测所有提供商的能力。1M只是下一轮实验配置，平台仍可处理较小文本任务。

遇不支持图像的模型：可用文本资料继续但显式标图像未分析，必要时请求支持图像的执行配置或用户补文本；同样请求不无限重试。不可把未读图像编成证据，也不把400归因为预算耗尽。

## 6. Agent3：有效目标、可检验因果与适度门槛

### 反馈与当前票面

Feedback增加kind（supplement_fact/change_expected/acceptance/reject_hypothesis）与显式observed/expected/steps；允许纯文本，未能确定kind时unknown，保留原文而非强猜。单次反馈允许同时提供多个显式字段，kind仅作主要意图提示，不限制补事实与改预期同时发生。InputRevision通过`merge_revision(parent, feedback)`生成完整有效票面：未提供字段继承，显式清空用clearFields表达，附件合并按ID去重。来源与父版本保留。parentRevisionId必须指向输入版本而不是attemptId；attempt关联另存。未知parent或重复feedbackId内容不一致要明确报冲突，不静默选字典序最新文件。附件明确撤销用removeAttachmentIds，历史不删除。

报告模式必须能实际二次执行：CLI新增 `resume --execute`，默认仍可只预览恢复决策；`--execute` 传apply_fix=false运行分析并保存新轮报告，`--apply-fix`保留显式补丁授权。没有编辑授权时不可借续修调用编辑器。HTTP如提供续跑入口复用同一应用服务和模式参数。

用户确认的预期与模型原因猜测分别存储。下一轮提示词必须显示本轮目标、变化与未变项。用户明确按交互稿移除开关时，弹窗钩子可列附带风险，但不能替换为本票主修法；发现更高优先规范冲突应解释并阻断相关决定。模型可推翻原因猜测，不能自行改写验收目标。

### 因果与证据

复用现有Evidence、Hypothesis、RootCause；首期只为会影响结论/修法的关键主张增加轻量Claim，不逐句建立知识图。新增Claim：claimId、statement、role（fact/hypothesis/conclusion）、evidenceRefs、assumptions、status（supported/conditional/unverified/refuted）。源码片段逐字校验只确认引用真实性；设备返回、时序、CSS实际渲染或用户看到的文案，缺运行观测时保留conditional。

模型最终摘要必须区分已确认事实、候选机制、缺少的区分证据、建议下一步；附带健壮性风险单列。程序只检查引用/字段/版本一致性，不冒充因果裁判。不得全局规定“静态分析一律不能supported”：确定的参数传反/文案key错误可以有充分源码证据；需要运行前提的性能、设备和时序主张才保留conditional。不自动给每票增加一次reviewer调用；复用现有分析收尾。

### 问题与编辑门槛

引入`questions`列表，每项id、kind（blocking/choice/verification/follow_up）、relatedClaimIds、reason、requestedEvidence。首期以单票为授权单位，不开发问题—文件—子补丁的细粒度授权引擎：与当前修复目标有关的blocking或choice阻断该票编辑；只有明确属于其它问题的follow_up才不阻断。relatedClaimIds先是可选证据关联，缺失时对blocking保守阻断，不能因无ID漏过。verification和follow_up保留报告，不要求从模型输出消失。

兼容策略不是同时维护两套：统一升级契约与全部prompt/样本/解析。旧openQuestions文本可继续供人阅读但由结构化questions生成，程序不再用其是否为空授权。区分外部历史产物和本次模型响应：旧外部契约版本明确不支持；新版本模型漏questions/claims时是分析输出不完整，允许一次有界格式修复，仍失败则保留已取得证据并报告incomplete，不静默补空数组放行。

报告模式照常产出分析，不因门槛不通过视为运行失败；分别显示analysisStatus、actionability和验证范围。不能因为applyFix=false产生补丁；补丁模式依然有独立授权与隔离基线校验。

## 7. 报告与评测可信度

人工评分记录先绑定product/defect/attemptId/reportDigest，claimIds在新版本有主张结构时可选；不得要求旧包补造Claim。reportDigest按规范化JSON或固定原始文件字节计算并写明算法，人工只录评分和依据，哈希由程序计算。旧评语若主张或摘要变化标stale，不自动平移评分。支持多条可接受路径，严格区分原先定义与事后修正；Alt命中单列，不反向改变历史原分数。

G0拆为产物完整性/声明诚实性与执行完成率。SDK失败诚实blocked不判“造假”；G0通过不判根因正确。定位、源码事实、机制、运行验证独立评价。继承Agent2候选的失败票不计Agent3新增定位成功。每次记录取样范围，本批24票不能外推全部230行。

报告中保留未决问题和证据等级；人工评测模板增加claim状态、当前目标、上游线索采纳/推翻、边界原因。代码真实性检查与业务人员裁判分开。

## 8. 优先级、交付与实验

P0：原文保全和质量结构、完整反馈目标、问题分类/门槛、因果声明与评分绑定。P1：Agent2小批续跑、技能可观察配置、模型能力manifest与模态错误处理。P2：在对照证据基础上调预算、排序和更复杂并发，不预设大模型一定解决。

历史基线产物先冻结；再于独立checkout/受控工作区按旧版本读取旧产物做对照，新版本不建设兼容层，也不覆盖用户业务仓。模型重测和代码开发不互相阻塞，配置基线能取得则保存；不能安全复跑旧版本时明确缺少该对照，不阻止工程完成。

先对同一组8—12张报告模式样本用约1M多模态模型重跑，固定HEAD/票面/技能/预算并记录变化；先比较旧输出与配置修正后的输出，再比较代码优化后的输出，避免同时更换所有变量而无法归因。旧模型不能执行图像的票单列可比性限制，图片是否成功读取本身不是根因正确。

最低固定案例：peitao04188（冲突）、09314（二轮移除目标）、02007（性能假设）；hcp03610（预期错配）、03691/11009071（缺信息规则）、04762（样式证据）；transport06318（旧评语）、09398（模式归属）；LED04084（外部设备假设）、01340（模态配置）。按业务条件选8—12票，不强制提供仓外代码。

工程验收：结构/控制流测试与正式入口夹具通过；真实SDK至少验证片段、技能和模态输入链。效果验收：业务人员逐主张核对错误与过度断言、目标遵守、报告可行动性、调查重复成本；无验收真值不设武断通过率。后续补丁模式仍需独立实项目验证，不属于这次报告模式的扣分项。

## 9. 推荐结构与实施边界

复用当前Pydantic、SDK和run_analyst，不重写工作区、检查或补丁。新增少量边界模块：Agent1 source_quality.py保真质量、cartographer/investigation.py分批调度、analyst/revisions.py完整票面合并。Claim/Question/Investigation均作为现有产物嵌套对象。代码位置、接口和测试见[实施计划](../plans/2026-11-16-three-agent-evidence-quality-implementation-plan.md)。

方案中的groupSize=8、字段命名和实验规模是推荐实现选择，不是本批测得最优值。当前业务材料没有原始工具轨迹，不能承诺自动获得全部历史searchedScopes；新运行开始准确记录即可。

## 10. 完整复审记录（2026-11-16）

本次补齐报告模式实际续跑、原始业务独立列、revision父链与附件撤销、分批复用键和预算边界；消除Claim与问题分类的隐式依赖。压缩为现有模块的顺序批处理及关键主张，不建设通用矛盾检测器或细粒度编辑授权引擎。验收拆分程序可验证不变量、真实模型语义评审、业务现场待验，避免fake返回预期字段就宣称效果提高。以上为实施前复审记录。当前实现、测试和待验事项见[当前实现与验收状态](../../architecture.md#验收状态)。

独立复审结论：修订后无重大落地矛盾；本次结论仅针对设计可实施性，不代表产品实现或业务效果已验收。
