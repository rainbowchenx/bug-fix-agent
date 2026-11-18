# 项目架构优化实施计划

> **执行说明**　本计划使用复选框追踪独立任务。收到实施指令后，使用 superpowers:executing-plans 按依赖执行。本次交付范围为计划。

**目标**　从正式入口能读清首跑、调查结果交接和单票续跑的完整流程，并用自动化检查约束新增代码的职责归属。

**架构**　保留 Agent1 和 Platform 两种交付。Platform 的 workflow 负责批次、反馈和续跑，Agent2 和 Agent3 各自负责业务决策，SDK 负责模型执行。测试、评测和发布按用途归位。

**技术栈**　Python ≥ 3.11、Pydantic、LangGraph、Claude Agent SDK、FastAPI、pytest、现有构建脚本。

**方案**　[项目架构优化方案](../specs/2026-11-18-project-architecture-refactor-design.md)

**计划日期与基线**　2026-11-18，`main` 的 `cfcb8a1`。交付行为参照 [Agent2 无损交接与 Agent3 收敛设计](../specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md)及其[实施计划](2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md)。执行时若主分支已有后续改动，先据实更新基线与文件引用。

## 全局约束

- 保留正式 CLI 命令、HTTP 合同、`three_agent` 图 ID、产物 schema、已有运行目录与反馈读取方式。内部调用入口和离线评分脚本路径允许随迁移统一调整。
- 保留 Agent2 逐票调查、组身份、完成判定和失效条件。R10 维持暂缓。现有 JSON 收尾在满足会话和预算条件时最多两轮，原响应和格式修复证据分别保存。
- 保留报告默认只读、显式授权编辑、上一轮证据注入、提问账本、候选验证、补丁基线、用户手工验收。首跑的显式环境配置与续跑的 CLI 授权分别按基线验证。
- 复用现有模型、存储和工作流。目录变动、业务职责抽取和验证任务分别审查。发现需要改变业务结论的问题，单列缺陷和验收。
- 以下 `python` 命令使用仓库支持的开发环境解释器。工程回归使用确定性的 SDK 替身或离线样本。真实项目复验单列。

## 任务依赖与评审重点

| 优先级 | 任务 | 前置依赖 | 独立交付 |
| --- | --- | --- | --- |
| P0 | T0 记录基线 | 无 | 测试、入口、构建、评分证据 |
| P0 | T1 抽出反馈与续跑用例 | T0 | CLI 变薄，续跑行为一致 |
| P0 | T2 统一报告发布 | T1 | 首跑和续跑复用汇总与发布 |
| P1 | T3 收拢 Agent2 交接 | T0 | SDK 输出及 Agent2 结果分离 |
| P1 | T4 提取 Agent3 单票流程 | T1、T2 | 首跑和续跑复用逐票尝试 |
| P1 | T5 固化架构规则 | T2、T3、T4 | 依赖检查和架构说明 |
| P1 | T6 目录归位 | T0 | 测试、评测和打包目录清晰 |
| P2 | T7 文档入口和归档索引 | T5、T6 | 根 README 指向当前入口，历史证据可查 |
| 收尾 | T8 全量复验 | T0–T7 | 工程验收记录及实仓复验记录 |

单工作区建议依次执行 T0 到 T8。T3 和 T6 可各自评审。T6 涉及较多路径改动，合并时与其他任务涉及的测试文件错开。

| 高风险输入或失败场景 | 必须验证的行为 |
| --- | --- |
| 用户重复导入同一反馈，或写锁已被另一续跑持有 | T1 保持反馈幂等和忙退出，父轮不回退 |
| 汇总 JSON 损坏或落后于已提交快照 | T2 恢复已提交结果，保留其他票，失败的快照提交不推进 latest |
| SDK 同组输出同时包含合法条目、畸形字段和预算停止 | T3 保留合法结果及来源，部分组保持部分状态，零预算可加载已完成组 |
| SDK 会话失效，用户补充有效，第一版候选检查失败 | T4 带上下文新开会话，满足证据与授权时可以编辑，最终候选独立统计检查 |
| 从源码树之外运行交付包，或脚本依赖被移动的夹具 | T6、T8 验证图入口、资源路径和离线评分 |

## T0 · 确定可重放基线

**范围**　`pyproject.toml`、两份 LangGraph 配置、`packaging/build.py`、`packaging/eval_agent{2,3}.py`、`tests/`、`test/fixtures/`。基线输出写到本次验收临时目录，交付时记录基线提交和命令。

- [ ] 保存 `git rev-parse HEAD`、环境版本、选用的 extras，运行 `python -m pytest --collect-only -q` 和 `python -m pytest -q -ra`。保留测试节点 ID、结果及跳过原因。
- [ ] 运行 `bugfix-agent --help`、`bugfix-platform run --help`、`bugfix-platform feedback --help`、`bugfix-platform resume --help`，记录正式入口和参数。用临时根运行 CLI、HTTP 和图入口的现有回归，记录产物路径、退出语义、默认只读和显式修复的行为。
- [ ] 准备一份 Agent2 固定批次、微型仓及真值，一份 Agent3 固定报告及人工真值。以原脚本跑一遍并保留评分和输出。Agent2 使用 `--mode heuristic`，对比路径、覆盖和来源等业务字段。Agent3 固定输入，分数、分母和报告摘要应精确一致。
- [ ] 清点测试、夹具生成器、构建验证、用户文档中的活跃路径。运行 `python packaging/build.py all --skip-exe`，记录两类 staging 内容。完整 Agent1 可执行包在发布环境单列。

**验收**　测试和评分输入可重放，能说明每个已知跳过或受环境限制的检查。运行本任务的结果属于实施证据。

## T1 · 抽出反馈导入和续跑用例

**范围**　新增 `platform/bugfix_platform/workflow/resume.py`，修改 `platform/bugfix_platform/cli.py`、`tests/platform/test_repair_cli.py`、`tests/integration/test_quality_report_flow.py`。复用 `agents/analyst/{feedback,feedback_document,sessions,attempt_store}.py`。

**接口**　`import_run_feedback(root: Path, source: Path) -> InputRevision`。续跑使用 `resume_defect(root: Path, defect_id: str, revision_id: str | None = None, *, execute: bool = False, apply_fix: bool = False, on_decision: Callable[[SessionDecision], None] | None = None) -> AnalysisReport | None`。预览沿用 `sessions.resume_from_store` 写出决策，发出回调并返回 `None`。执行在分析开始前发出决策回调，成功后返回合并的报告。

- [ ] 复用现有 CLI 续跑和历史合并用例。缺失的入口覆盖集中补在原测试文件，断言同一反馈返回相同 revision、预览不调用 Analyst、不新增 attempt、`--execute` 保持报告模式、忙退出时不写产物。
- [ ] 运行 `python -m pytest -q tests/platform/test_repair_cli.py tests/integration/test_quality_report_flow.py tests/platform/test_revision_targets.py`。保留迁移前行为。
- [ ] 将 JSON/Markdown 反馈导入、锁、父轮选择、会话选择和 Agent3 调用迁到用例模块。维持同一锁域。CLI 映射参数、原退出码、错误文本和决策 JSON。旧测试的替身应迁到实际依赖注入点。
- [ ] 复跑本任务命令及 `python -m pytest -q tests/platform/test_repair_entry.py tests/integration/test_quality_review_hardening.py`。核对未知票、修订版错误、显式修复及重试失败场景。独立提交。

## T2 · 统一报告聚合和发布

**范围**　`platform/bugfix_platform/workflow/{resume,graph,persist}.py`、`cli.py`、`agents/analyst/{run,report,report_store,analysis_store,attempt_store}.py` 中的相关调用。测试复用 `tests/platform/{test_repair_cli,test_repair_report_store,test_langgraph_workflow,test_http_runs_api}.py`。

**接口**　在 `agents/analyst/report_store.py` 复用或形成 `merge_analysis_report(current: AnalysisReport, previous: AnalysisReport | None) -> AnalysisReport` 和 `publish_analysis_report(root: Path, report: AnalysisReport, *, already_locked: bool = False) -> None`。workflow 决定何时发布、是否合并及轮次文件；report store 负责汇总、JSON/Markdown 写入与已有恢复规则。

- [ ] 覆盖汇总损坏、汇总落后于 latest、保留其他票、并发写者、快照提交失败。断言 `summary.total`、`summary.byOutcome` 与最终票集一致，历史 `logRef` 可读，报告模式与授权字段保留。首跑经 CLI、HTTP、独立 LangGraph 调用均可读取落盘产物。
- [ ] 先提取合并与渲染，再收拢写入调用方。保留图节点的渐进产物、失败后可取得部分产物的语义。清理 CLI 对图已发布文件的重复覆写。明确首跑 Node 发布与 Agent3 快照提交的锁边界，已有锁的路径直接复用，避免重复加锁。发布时避免用过期内存报告覆盖已提交的新尝试。
- [ ] 保持直接调用 `run_analyst` 时已有的报告返回与 Markdown 交付。正式 workflow 调用通过约定把汇总发布交给 workflow。继续以已提交 attempt 和快照为恢复依据，失败提交不推进 latest。JSON 和 Markdown 分别原子替换，恢复时可重建派生文件。
- [ ] 运行 `python -m pytest -q tests/platform/test_repair_cli.py tests/platform/test_repair_report_store.py tests/platform/test_repair_entry.py tests/platform/test_langgraph_workflow.py tests/platform/test_http_runs_api.py tests/integration/test_repair_feedback_flow.py`。用真实文件系统的回归验证锁和写入顺序。独立提交。

## T3 · 收拢 Agent2 SDK 与调查交接职责

**范围**　`platform/bugfix_platform/sdk/{cartography,match_payload}.py`、`agents/cartographer/{run,investigation,investigation_store,match}.py`，新增 `agents/cartographer/handoff.py` 归并结果解释。测试移到实现所属侧，正式集成调用保留。

**接口**　组调度继续消费 `CartographyRunner(CartographyRequest) -> CartographyResult`。由 Agent2 提供该结果适配。SDK 返回内部 `CartographyResponse`，携带解析的对象或空值、终止与错误信息、调用与费用数据、观察到的路径、skill 读取和原始输出引用。SDK 通过窄的可选记录接口发出原始响应、格式修复与工具记录事件，Agent2 注入现有调查记录器。

- [ ] 先固定混合合法/坏数据、空候选、未调查/部分/完成、费用与证据归属。分别验证预算触顶有余量时至多两轮收尾，以及无余量时保留可用结果并停止。核对原始响应和格式修复文件引用。
- [ ] 把条目容错、类型校验、证据确认、已调查票归属、结果合并、回退判定迁到 Agent2。保留所有仍需的逐票追踪、来源、诊断和进度字段。SDK 继续处理工具、解析及会话收尾，移除对 Agent2 store 和 match 的反向导入。继续由 `investigation.py` 管理分组身份、协议版本和复用条件。
- [ ] 运行 `python -m pytest -q tests/platform/test_sdk_billing.py tests/platform/test_cartography_sdk.py tests/platform/test_sdk_match_normalization.py tests/platform/test_investigation_batches.py tests/platform/test_investigation_progress.py tests/platform/test_investigation_store.py tests/integration/test_handoff_feedback_convergence.py`。验收正式首跑的合法 SDK 条目可进入 Agent3，零预算可恢复已完成组，未完成组可续跑。独立提交。

## T4 · 提取 Agent3 的逐票尝试流程

**范围**　`platform/bugfix_platform/agents/analyst/{run,context,continuation,claims}.py`、新增 `agents/analyst/attempt.py`、`platform/bugfix_platform/sdk/analyze.py`。沿用已有 evidence、checks、workspace、sessions 和报告归属。

**接口**　保留 `run_analyst(...)-> AnalysisReport` 及现有注入点。在 `attempt.py` 形成 `run_ticket_attempt(ticket: BatchTicket, inputs: TicketAttemptInputs) -> dict[str, Any]`，`inputs` 承载本批已初始化的运行器、单票上一轮选择和显式传入的批次计数状态。单票在原扣减位置更新剩余额度、来源和 skill 读取，批次层统一汇总，即使该票后续抛异常也能保留已经发生的额度消耗。

- [ ] 复用正式入口案例固定两轮：首次需要补充，第二轮读取前次证据和问题账本；会话失效可降级；有效反馈且授权时进入编辑。断言第一轮日志仍可读，最后一份 PatchSet 只用自身适用检查得出结论。
- [ ] 把 `run_analyst` 内逐票闭包提取为明确入口。批次继续负责构建共享运行器、选择目标票、消费额度、隔离异常和形成批次报告。单票内按顺序呈现本轮输入、路由与分析、证据门槛、验证和 attempt 提交。候选修复循环及已有辅助模块维持各自语义。
- [ ] 消除 `sdk/analyze.py` 对 `analyst.claims` 的反向依赖。将当前两条根因处理分支的业务规范化交回 Agent3，覆盖常规响应和预算停止时的部分响应。保持代码片段证据状态与原始 SDK 错误信息。
- [ ] 运行 `python -m pytest -q tests/platform/test_analyze_sdk.py tests/platform/test_repair_entry.py tests/platform/test_repair_patch.py tests/platform/test_repair_checks.py tests/platform/test_repair_context.py tests/platform/test_repair_continuation.py tests/platform/test_question_convergence.py tests/integration`。验收未授权时只有报告，授权且证据通过时存在可应用候选，混合失败检查仍标失败。独立提交。

## T5 · 把架构骨架变成可执行规则

**范围**　扩展 `tests/test_package_boundaries.py`，新增 `docs/architecture.md`。沿用现有 pytest 入口。若实际交付流水线分开配置，将该测试加入它现有的工程回归步骤。

- [ ] 增加源码依赖检查，覆盖模块内和函数内导入。断言契约无 Agent 反向依赖，SDK 无入口、workflow 或 Agent 反向依赖，CLI/HTTP 通过 workflow 委派 Agent 执行。报错定位文件、行号和被违反的规则。沿用现有包边界和技能资源检查。
- [ ] 写架构说明，按首跑、Agent2 交接、Agent3 续跑三条调用路径给出文件入口。说明持久化写入者、恢复顺序，以及 SDK session、LangGraph checkpoint、逐票 attempt 分别能恢复什么。
- [ ] 运行 `python -m pytest -q tests/test_package_boundaries.py tests/integration`。可走读单票续跑从用例到业务决策的顺序，边界检查随工程测试执行。独立提交。

## T6 · 合并测试夹具并迁移评测工具

**范围**　`test/fixtures/{defect-batch,repos}/` 迁入 `tests/fixtures/`，`packaging/eval_agent{2,3}.py` 迁入 `evals/`。更新 `tests/{conftest,helpers}.py`、相关测试、`packaging/build.py`、夹具生成器、README、CLAUDE.md 和活跃评测指引。

- [ ] 用纯路径迁移保留夹具内容和评分算法。更新构建验证读取的缺陷样本、微型仓生成器及测试导入。历史设计、已发布报告及原始证据保留语境。去掉空的 `test/` 目录，并从 `evals/` 提供评分命令入口说明。
- [ ] 运行 `python -m pytest --collect-only -q`，与 T0 核对用例节点 ID，单列 T1–T5 新增覆盖。运行 `python -m pytest -q`。用迁移后的两条评分命令重跑 T0 输入，核对关键字段和分值。
- [ ] 运行 `python packaging/build.py all --skip-exe`。在源码树之外验证 Agent1 和 Platform 的入口及资源，保留开发、发布两份 LangGraph 配置各自的加载路径。迁移单独提交。

## T7 · 整理文档入口及实测归档

**范围**　根 `README.md`、`CLAUDE.md`、`docs/architecture.md` 和 `docs/field-eval/`。现有 ZIP 及其历史记录作为证据源。

- [ ] 从根 README 导向当前架构、工程测试、离线评分、构建和实仓评测。检查活动文档中的命令与路径。
- [ ] 在实测记录建立归档索引，记录批次、来源、关联评估和访问入口。只有归档位置已验证可读且副本校验一致后，才另行处理原有 ZIP。归档位置未确定时，索引指向当前文件，记录搬迁待定。
- [ ] 核对方案与实验记录链接、评分脚本命令和夹具入口可定位。独立提交。

## T8 · 交付验收

- [ ] **工程测试**运行 `python -m pytest --collect-only -q`、`python -m pytest -q -ra`，逐项解释相对 T0 的用例和跳过差异。记录 Agent1 独立入口、Platform CLI 首跑和续跑、HTTP 首跑、独立 LangGraph 的验证结果。
- [ ] **交付构建**运行 `python packaging/build.py all --skip-exe`，记录两类 staging 烟测。发布环境运行 `python packaging/build.py agent1`，验证可执行包。发布环境缺失时单独标记未验证项。
- [ ] **离线评分**重放 T0 固定用例，报告业务字段和评分变化。时间戳、会话标识、临时绝对路径按含义比较。发现业务差异时定位到具体变更和字段。
- [ ] **可读性审查**沿代码回答三件事：调查条目为什么保留，二次投递何时允许编辑，损坏报告从哪里恢复。验收记录列出各自入口、模块所有者和对应测试。
- [ ] **实仓配对复验**使用相同代码基线、同一批缺陷、同一模型配置与反馈输入，对比有效调查保留、Agent3 消费有效补充、重复提问、进入候选及业务验收。只有用户实际应用并验收的候选进入修复成功率。环境或人工材料未到时，记录待复验范围与缺失证据。

**最终记录**　按 T0–T8 回填提交、命令和结果。分别列出工程完成、构建环境待验和实仓待验。

## 执行记录

- T0 在独立的 `cfcb8a1` 工作树复跑，收集 550 个用例，545 通过、5 跳过。
- T1–T5 已接入正式入口。续跑、LangGraph、HTTP 和失败时保留输入产物的针对性回归共 27 项通过。新增的源码依赖检查覆盖函数内导入。
- T6 已核对 103 个夹具的新路径。测试收集保留原有 550 项，只增加 1 项边界检查。Agent2 的两个 device-web 固定用例评分和候选路径一致，Agent3 使用同一份转换到当前契约版本的脱敏报告副本，评分逐字节一致。
- T7 已添加当前架构和历史归档索引，原始 ZIP 继续使用仓库中的位置。
- T8 全量为 546 通过、5 跳过。跳过项与基线一致，涉及本地未入库 CSV 和未挂载的 peitao 仓库。Windows 环境运行 `python packaging/build.py all` 通过，Agent1 独立 EXE 实际生成 50 条缺陷，Platform 从独立 staging 加载工作流图。该环境的 `--skip-exe` 路径因 staging 内没有预构建 EXE 无法完成，验收使用完整构建。
- 调整决策：根因字段的结构规范化由共享报告契约持有，Agent3 持有证据绑定和结论判断。反馈用例保持 LangGraph 可选依赖，发布包仍从原入口加载图。部分测试同时引用业务模块和夹具目录，两类改动共同提交以保持提交可运行。
- 待实仓复验：同一模型与同一反馈下的 Agent2 调查质量、Agent3 二次收敛和用户修复验收。
