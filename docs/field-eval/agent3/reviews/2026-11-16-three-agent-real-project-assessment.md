# 四产品线真实运行产物复评：Agent1 / Agent2 / Agent3

日期：2026-11-16（Asia/Shanghai）。性质：产物与当前平台代码审查，非业务修复验收；未修改产品代码、未运行模型、未应用业务补丁。

## 0. 用户补充的运行边界（2026-11-16更新）

用户已明确：本次运行选择约256K上下文、非多模态模型；图像请求失败属于本次模型配置选择，期望下一轮使用约1M上下文的多模态模型。具体模型名、实际可用窗口及服务端工具/图像支持仍需在重跑时记录，不将“1M”作为已验证能力或平台硬性最低配置。

用户明确要求Agent3禁止改码，仅产出完整报告。applyFix=false、无补丁、未进行补丁应用/业务验收符合测试范围，不是实现失败；本批判据是报告完整性、分析依据、目标一致性、未决问题与后续建议质量。24份allowed=false仅用于检查潜在改码门槛，不作为本轮运行不合格或补丁产出率为零的扣分项。

因此调整解释：LED相机票的图像400首先归为运行配置不适配；平台能力检查/明确降级是改进建议，不将此次错误全部归责Agent3。256K是否造成某票定位/因果判断问题尚无受控证据，不能由此推断换1M会自动修复；固定16票选取、原文裁剪、目标混淆和陈旧评语仍需独立处理。

后文“未证明修复闭环有效”只说明证据范围，不否定本次只出报告的目标。根因与未决问题的一致性、二轮目标漂移、原文缺失、调查覆盖仍是可据本批评估的实现问题。

## 1. 总判断

这批材料证明平台已能在真实项目中形成具有实际导航价值的调查与建议，但不足以证明完整修复闭环有效。Agent1 的三字段抽取基本保真，完整原文与语义质量仍有缺口；Agent2 应保留逐票调查，但当前偏浅搜索、覆盖受限；Agent3 有跨层推理与自主重查能力，主要风险是把合理候选机制写成确定根因、所有开放问题都阻止改码，以及二次反馈未坚持用户确认的验收目标。

本轮最优先不是增加agent数量或普遍增加预算，而是修正目标与事实的表达、保留输入上下文、区分阻断问题与验收待项，并用真实补丁验收验证收益。

## 2. 来源、版本与证据等级

用户授权后执行 `git fetch origin`，从 `90e4744` 快进到 `d668185`；本地既有改动保留。最新两次提交仅新增/更新交付包，运行声明的平台版本是 `90e4744`。针对 agent1/contracts/platform 的差异忽略行尾后无本地实质差异。

数据源：[交付压缩包](../../../../runs-2026-11-16/bugfix-runs-2026-11-16-交付包.zip)。安全检查路径后解压到临时目录，仅读取 CSV/JSON/Markdown，不执行归档脚本、pickle或其它可执行内容。先前 `docs/业务缺陷分析.zip` 属于旧资料，本次不混入统计。

配套成果：

- [机器可读统计与压缩包SHA256](2026-11-16-artifact-statistics.json)
- [24票独立复评CSV](2026-11-16-ticket-reassessment.csv)
- [评测方法](../2026-11-15-real-project-evaluation.md)
- [修订方案](../../../superpowers/specs/2026-11-15-agent3-repair-feedback-design.md)
- [实施计划](../../../superpowers/plans/2026-11-15-agent3-repair-feedback-implementation-plan.md)

证据按以下层次解释：

1. 本次直接可核实：JSON/CSV数值、字段、版本、上下游结论、代码控制逻辑和材料之间的矛盾。
2. 运行者记录：业务源码grep/Read复核、成本/turns、业务skill存在性。归档未含业务源码和完整运行轨迹，不能把作者的复核记录冒充本次独立源码验证。
3. 尚待验证：真实触发条件、运行时因果、改码可行性与业务验收。

README明确03档案是attempt最终主张摘录，不是完整SDK逐步会话；sessionId不意味着本机能访问该会话。包内未附原始attempt.json、run.log、score.json、补丁、执行日志和真实验收记录。主报告提及的部分原目录路径未随交付视图一起提供。已具备足够材料做本次分析，不要求用户重新整理全部资料才能继续。

## 3. 样本和分母

| 产品线 | 原始CSV行 | Agent1条目 | strict/locatable/needs_info | Agent2有候选 | Agent2 complete/partial/未调查/状态缺失 | Agent3分析结果 |
|---|---:|---:|---|---:|---|---|
| peitao | 19 | 19 | 18/1/0 | 19 | 16/0/3/0 | 5 plan_only，1 blocked |
| transport | 37 | 37 | 34/0/3 | 26 | 15/1/21/0 | 6 plan_only |
| hcp | 37 | 37 | 25/4/8 | 27 | 15/1/21/0 | 6 plan_only |
| led | 137 | 40（11-12复用） | 37/2/1 | 39 | 0/0/0/40 | 5 plan_only，1 blocked |
| 合计 | 230 | 133 | 114/7/12 | 111 | 46/2/45/40 | 22 plan_only，2 blocked |

三条新Agent1批次93行均进入batch；LED的97行差额不能视为当前Agent1漏掉或筛掉，因为其40票明确复用旧批次。四条batch均没有hard_reject/security/excluded/duplicate样本，不能据此评估这些硬筛策略的实际误拒率。

Agent3每线仅选6票，总24票全部strict；对应6票切片与全量相同票的内容一致。6票切片的clusters仍包含批外成员，说明裁剪元数据还不完全一致。报告覆盖应称24/24已投递票，不称覆盖全部230条源工单。尚未覆盖needs_info、仓外判断、已应用补丁后修复等重要真实场景。

所有24票 applyFix=false、patch=null、verifyStatus=skipped、suggestedVerify.executed=false。22/24表示形成了分析建议，不能叫修复成功率；2/24表示未完成首轮分析。没有业务验收，成功率和回归率均为N/A。

## 4. Agent1：抽取保真尚可，资料保真与质量判断不足

### 4.1 已有价值

逐票对照原始CSV，归一空白后，非空 observed/expected/steps 与原文相应段落未发现差异。这说明本批没有证据表明Agent1改写/串写了三字段。原始工单自身存在用例和现象错配，应与Agent1错误区分。

### 4.2 当前缺口

新产物93票的sourceObserved/sourceExpected/sourceSteps与提炼三字段完全相同。当前 `cluster.py` 也直接复制蒸馏结果；这些字段不能替代完整description或原文稳定引用。LED40票没有source字段是旧产物差异，不是本次新版本生成失败。

133票原文中70票含非空测试数据、77票含非空前置条件；24张分析票分别有15票、15票，但batch没有专门字段传递。全部133票attachmentRefs为空或缺失。原文中的页面回放链接、附件说明不等于附件已取得，也不能因为source字段存在便宣称信息已完整保留。

| 例子 | 事实 | 影响 |
|---|---|---|
| peitao BGCM2026110304188 | 用户管理Please wait；步骤和预期却是键盘退出安装模式；原问题栏有pagespy链接 | 真实输入冲突未标注，回放线索丢失 |
| hcp BGCM2026110303610 | ONVIF跳转；步骤/预期却是ISUP添加设备 | explicit不等于可靠验收目标 |
| LED BGCM2026051104842 | 颜色回读；expected是RGB采集与系数上传全流程 | 旧输入冲突，不能归因当前改写 |
| hcp BGCM2026110303691 | “添加onvif设备报错没有错误提示”被C1e要求报错细节 | “没有错误提示”本身就是缺陷，形成规则误伤候选 |
| hcp BGCM2026111009071 | PDF排行上下顺序、bottom排序和地图偏移 | 已有具体对象和比较关系，C1c仍判模糊，规则过粗 |

源码对应：[distill.py](../../../../agent1/bugfix_agent1/defect_batch/distill.py) 的段落提取、[cluster.py](../../../../agent1/bugfix_agent1/defect_batch/cluster.py) 的输出裁剪、[expect_quality.py](../../../../agent1/bugfix_agent1/defect_batch/expect_quality.py) 的非空即explicit、[rules.py](../../../../agent1/bugfix_agent1/defect_batch/rules.py) 的C1c/C1e。这里只确认规则机制与具体分流，不推断12票needs_info全部可修。

建议：完整原文/稳定引用优先；提炼保留字段位置，另表达预期相关性与冲突；为“错误反馈缺失”和具体比较关系增加语义例外；needs_info保留有限调查入口。

## 5. Agent2：逐票导航有用，但仍不是可恢复的调查交接

### 5.1 覆盖与调查密度

93张新票中46 complete、2 partial、45 not_investigated。当前每次最多16票进入prompt；19票新批次也有3票未调查。40张旧LED票没有状态。133票searchedScopes/openQuestions全部为空或缺失；来源共293候选（grep207、codegraph85、claude_md1），来源标签不证明工具实际调用或因果关系。

当前complete主要表示模型返回该票且有候选，不表示根因完整。`partial=false`、全量条目存在、某票有候选是三个不同事实。hcp与LED的partial=true应保留，salvage拿到合法JSON不等于完成调查。

### 5.2 不应删除逐票调查，也不能把它当Agent3上限

- peitao具体页面/协议/权限入口帮助将中文现象接到业务代码，保留价值。
- peitao BGCM2026102902007：Agent2给group噪声，Agent3找到remoteCtrl。
- hcp BGCM2026110304123/04635：Agent2给同一组loading/Downloading/FaultLoading词面候选，Agent3分别找到HotSpare/LinkageConfigForm。
- transport BGCM2026102809398：Agent2已有postHVT方向，Agent3转到alarmWorker；不能说是错误上游候选带偏。
- transport BGCM2026102906318：Agent2是dataDocking词面噪声，Agent3重查videoEpolice；不能由两端结果推导具体采纳过程。

因此“Agent2候选是定位天花板”“错误线索是跑偏主因”均超出本包证据。应记录使用/否定了哪些线索、搜索成本和重查范围，再判断增益。

当前 [cartography.py](../../../../platform/bugfix_platform/sdk/cartography.py) prompt明确偏浅覆盖，why解释相似性而非根因，且限制逐票沿imports/callers深入。这个实际角色与期望的逐票前置调查存在差距。建议允许针对高价值票的小范围调用链调查，记录事实/假设/排除项；按小批可续跑覆盖，不简单放大一次上下文。

### 5.3 技能与成本

四线boundSkills都是4个包内技能。运行说明报告仓内业务skill因缺profiles未被注入，与当前 [skill_inject.py](../../../../platform/bugfix_platform/sdk/skill_inject.py) `allow_unprofiled=False` 一致；但归档无原skill文件及原始调用记录，不能独立证明技能是否由SDK原生另行发现/实际调用。

可对业务skill补profile并显式传入目录做小范围对照，先证明发现→读取→执行，不承诺“一行字段”自动提升正确率。微前端嵌套项目技能发现也应检查作用域，不只看根目录。

运行说明的新Agent2费用：1.44+1.49+13.19=$16.12；LED $11.65是旧产物历史成本，不属于本轮增量。无完整usage账本，不能核验所有salvage是否计入。Agent3成本未完整提供，不能计算全链路单票成本或质量/费用比。

## 6. Agent3：有调查能力，尚需校准因果和行动资格

### 6.1 值得保留的能力

能够跨页面/状态/IPC/i18n/全局主题追踪；能明确报告失败，不强行包装完成；能跳出错误Agent2候选；部分票主动识别原始预期错配。

静态材料中较强的分析方向包括：

- peitao 08455：翻译key层级与日志导出消费链。
- peitao 00881：ONVIF禁用控件与保存报文仍携带字段的矛盾。
- peitao 04188：分页缺终止字段与loading清理路径。
- transport 00211：图形绘制、导流带ID与列表回写之间的链路。
- hcp 04635：缺少保存loading/防重复提交，与邻近实现对照。
- LED 04842：catch丢return、空值读取和回读失败处理。

这些是有价值的、可检验的分析；尚非本次独立确认的业务根因或修复成功。

### 6.2 把静态事实与触发前提分开

- peitao BGCM2026102902007：全表回写/大量选项是事实候选，但“主线程阻塞约2s、点击排队落错行”需要性能轨迹；openQuestions也承认可能是请求等待。summary不应写成已证实。
- LED BGCM2026051104084：summary断言初始化将设备颜色重置红色；openQuestions又承认设备服务不在仓、行为未知。应表述为初始化副作用假设，而非确定根因。
- hcp BGCM2026110304762：CSS规则链有导航价值，但报告尚未读取完整本地style，也未确认实际computed style/截图颜色；不能据grep宣布“全局缺规则就是根因”。
- hcp BGCM2026110302952：固定100×100和两行文案并不直接证明溢出；缺实际渲染信息且原流程冲突。
- hcp BGCM2026110303220：存在QuestionID范围和splice(-1,1)风险，不证明用户所说未翻译就是这些风险触发。

当前摘要与openQuestions必须使用同一不确定性口径。建议每条因果边记录“源码已见/现场待证/外部未知”，只请求能区分假设的最小证据。

### 6.3 编辑门槛全部拒绝，设计实现有过严之处

24份03档案均allowed=false；24票都有openQuestions，部分还missing evidenceRefs。当前 [evidence.py](../../../../platform/bugfix_platform/agents/analyst/evidence.py) 对任意非空openQuestions一律拒绝。

本轮是分析模式，没有实际开改码，不能把0/24叫补丁产出失败；但它暴露了行动门槛：即使只剩“同类文案要不要顺便改”或“无实机待验”，也会与根因未明同等阻断。建议拆分真正改变修法的blockingQuestions、可独立处理的followUps、验证待项；只让关键未决问题阻止相关改动。这也修正此前设计/审查把所有开放问题统一当阻断的过度约束，不能为了放行而要求模型隐藏问题。

snippet存在/逐字吻合只能证明引用真实性，不能证明机制成立。当前 [run.py](../../../../platform/bugfix_platform/agents/analyst/run.py) 中confirmed/causal的表达应与模型解释和事实级别分开，防止文本核对被误认为程序证明根因。

### 6.4 两票分析失败应按真实原因修复

- peitao BGCM2026102809314：无可解析JSON。包内未提供足够原始流区分没有输出、格式异常或解析遗漏，不能直接承诺提高轮数能解决。
- LED BGCM2026051201340：JSON明确是API 400“当前模型仅支持文本，不支持image input”。应做模型/工具模态能力适配或更换支持图像的模型；不应继续按max_turns建议加预算。

两票诚实记blocked是优点；这说明具体失败没有伪装成分析完成，不等于所有来源、技能执行和事实均已独立验证。

## 7. 二轮案例：应以用户确认目标为主线

peitao BGCM2026102809314 的05记录用户明确补充“交互稿已删除开关，整体移除”。二轮却建议把before-change迁到on.change保留开关，并将移除需求降为产品待确认。本包没有更高优先产品证据推翻用户补充，因此不能将该案例评价为成功的反馈纠偏。

common-form透传props、本仓没有实现before-change，也不能证明外部switch不支持该钩子；档案自己承认外部实现未知。这个潜在代码问题可另列，不能替换当前验收目标。

当前 [feedback.py](../../../../platform/bugfix_platform/agents/analyst/feedback.py) 将所有feedback.text塞到observed；[context.py](../../../../platform/bugfix_platform/agents/analyst/context.py) 使用新revision时不完整合并原expected/steps。建议反馈类型明确为补事实/改预期/报告验收/否定原因猜测，保留父版本并组装完整有效票面。目标变更要在prompt和报告显式展示。

模型确实读到了“移除”要求，所以该案例不能完全归咎字段结构；同样需要推理行为约束：质疑用户原因猜测合理，否定已确认的产品目标需要证据或明确请求澄清。

## 8. 评测报告需纠正的结论

### 8.1 前缀评分可复算，但不等于根因质量

| 产品线 | 主前缀loc@1 | 主前缀loc@3 | 加声明Alt后的loc@3 |
|---|---:|---:|---:|
| peitao | 6/6 | 6/6 | 6/6 |
| transport | 2/6 | 2/6 | 3/6 |
| hcp | 4/6 | 4/6 | 4/6 |
| led | 2/6 | 5/6 | 5/6 |
| 合计 | 14/24 | 17/24 | 18/24 |

以上按归档JSON直接重算，未调用旧评分器。当前 [eval_agent3.py](../../../../packaging/eval_agent3.py) 不处理expectPathPrefixAlt；交通OSD的Alt命中不会进入其机器分数。HCP门禁两票的Resource与AccessControl真值、LED亮度计跨主进程/子系统与renderer宽前缀都需人工重审。合理替代定位不因未中原目录就判错。

定位分数还包含失败票继承的Agent2候选，如peitao升级票宽前缀src/view/命中；不能算Agent3新增调查成功。应同时报告Agent2基线与Agent3增量，并将未完成票的候选命中与完成分析分开。

### 8.2 人工评语与当前输出没有绑定

- transport BGCM2026102906318：04/CSV说只围绕bSupportPostNetScreens；实际JSON/03已详细讨论relatedLaneCount→changeLaneNum→旧XML/重绘，并排除无车道数字段的personRunRedLight。需要重审，不能直接称答非所问。
- hcp BGCM2026110303220：04说未走$t()/key拼接错；JSON/03是QuestionID超范围及splice(-1,1)。不是同一机制。
- LED BGCM2026051104084：CSV/04复核摘要还写回读缺失/colorMap；当前报告说回读存在、映射正确，怀疑初始化污染。不是同一机制。
- transport批次报告的成功/失败案例ID和业务描述串位，甚至引用了peitao的码率案例；不能拿其案例段作真值。

后续评语绑定attemptId + report摘要 + claimId；若主张变更，旧评分自动待复核。原始材料优先于总报告，不能以同一模型反复生成的档案相互证明。

### 8.3 G0、G3与verdict解释

诚实记录SDK失败与“成功完成分析”应分成两个指标；process_fail不等于幻觉或造假。反之G0通过不证明根因真实。grep确认符号、路径和分支存在，最多支持代码事实；不能把所有非空summary或有关键词的结果叫机制全验证。

transport 09398的alarmWorker机制究竟是否答非所问，仍需确认实际模式和数据链；真值postHVT目录本身不足以判定。06318已有明显旧评语问题，更不能照搬“两票确定跑偏”的总结。

## 9. 优先级与下一轮验证

| 优先级 | 改进 | 直接验收 |
|---|---|---|
| P0 | 反馈目标与事实/原因猜测分开 | 升级开关明确移除目标不能被换成修弹窗；不确定冲突单独报告 |
| P0 | blockingQuestions与跟进/验收项分开 | 根因/预期未明仍阻断；独立可修文案不因无关跟进问题永远拒绝 |
| P0 | 摘要因果与证据等级一致 | 外部设备重置红色、性能2s等在无观测时标假设，报告不自相矛盾 |
| P0 | 评分绑定实际产物、修正LED失败原因 | 三个陈旧评语重审，Alt可计，模型图像400与预算分开 |
| P1 | Agent1原文和质量标注 | 原文/问题链接/前置条件/测试数据可按需读取；错配不自动explicit |
| P1 | Agent2分组覆盖与调查交接 | 超16票有续批或明确待调查；事实/假设/排除/下一步可恢复 |
| P1 | 业务skill发现、适用性与实际读取 | HCP一张i18n票对照；证明读取/应用，不能只看boundSkills |
| 运行配置（用户已澄清）/P1健壮性增强 | 下一轮约1M多模态模型；记录能力与限制 | 首先修正运行配置，平台明确处理不支持模态；不是本批Agent3质量扣分 |
| P2 | 再按观测优化预算/候选排序/成本 | 固定票、HEAD、模型配置比较耗时、准确性和增量价值 |

第一组补测建议：

1. 选2—3张低歧义且业务预期明确的票，开启generate-patch，审阅完整补丁、工程检查与实际行为；无环境保留未验范围，不再只看plan_only。
2. 升级开关按真实交互稿重做二次反馈；另选已应用补丁后追加修复票。当前包只证明一次补充后的再分析，不证明已应用补丁的完整续修。
3. HCP的两个needs_info候选做有限调查，记录是否能从代码恢复证据，不预设都能改。
4. transport 06318/09398由熟悉该模式的人结合页面入口/协议/插件实际返回重裁；LED4084取得初始化前后回读日志。
5. 业务skill做一组可执行对照，补充完整轨迹/关键工具记录和最终候选/验收结果；无需提供完整业务仓。

本轮无须继续扩建复杂基础设施。先让少量真实票在目标明确、事实诚实、门槛适度的前提下交付并验收，才能判断此前工程闭环是否带来实际修复收益。

## 10. 本次核验记录

直接解析4份完整batch、4份六票batch、4份code-knowledge、4份analysis-report、4份cases、5个原始CSV、24份逐票档案集合及1份二轮材料；交叉核对源码中数据裁剪、调查覆盖、技能发现、编辑门槛、反馈组装和评测逻辑。统计与逐票CSV已生成。

未执行真实业务仓grep/Read、未复现UI/设备、未执行补丁应用或测试；包内“源码复核通过”保留为运行者记录。所有数据结论附此边界，不输出伪精确根因正确率或修复率。

## 11. 后续优化文件

已据用户补充形成[三Agent优化方案](../../../superpowers/specs/2026-11-16-three-agent-evidence-quality-design.md)和[具体实施计划](../../../superpowers/plans/2026-11-16-three-agent-evidence-quality-implementation-plan.md)。仅产出文档，尚未实施。
