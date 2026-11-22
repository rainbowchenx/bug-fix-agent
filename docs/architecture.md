# 当前项目架构

Agent1 独立导入和整理缺陷并输出 `DefectBatch`。Platform 消费这份产物，通过 Agent2 调查代码并通过 Agent3 交付报告。Pydantic 契约位于 `contracts/bugfix_contracts/`。

## 三条正式链路

- **首跑**由 CLI 或 HTTP 调用 `workflow/run.py` 的 `run_three_agent_workflow`。LangGraph 部署复用 `workflow/graph.py` 的同一张图。图校验输入和 Agent 产物，并调用统一报告发布。
- **调查交接**由 `agents/cartographer/run.py` 调度。分组和续跑进度在 `investigation.py`。SDK 在会话和预算允许时对漏票或重复 ID 做一次最多两轮的补查，`handoff.py` 保留已接受结果并校验补查内容。
- **反馈和续跑**由 `workflow/resume.py` 接收。它持有产物锁，导入反馈或确定续接方式和父轮。首跑和续跑都通过 `agents/analyst/run.py` 调用 `attempt.py` 的逐票尝试。逐票流程决定编辑资格、验证和当轮状态。

## 状态和恢复

- LangGraph checkpoint 保存批次编排位置，Claude SDK session 提供可选的对话续接。
- Agent2 在 `agent2/progress.json` 保存按唯一票统计的阶段和中断记录。每组的 `parse-result.json` 保存字段诊断和原始引用，首轮和补查响应分别归档。调查协议变化后，旧完成缓存失效。
- 已提交的逐票 attempt、分析快照及 latest 指针保存业务进展。汇总损坏后由 `agents/analyst/report_store.py` 从已提交快照恢复。
- 报告 JSON 和 Markdown 通过共享发布路径写出。首跑与续跑在同一产物根内使用同一排他锁协调逐票提交和汇总发布。
- 用户自己应用和验收补丁。报告默认不编辑，续跑使用显式授权开启编辑。
- 本地 `commit` 核对当前逐票快照、报告、补丁摘要和 Git 暂存内容。缺少补丁摘要的旧候选需要重新生成。

工程回归在 `tests/`，共用夹具在 `tests/fixtures/`。依赖方向由 `tests/test_package_boundaries.py` 检查。离线评分见 [evals](../evals/README.md)，构建入口为 `python packaging/build.py`。

## 验收状态

当前可用于人工复核的只读试点。最近一次代码全量离线回归为 568 项通过、5 项跳过。跳过项依赖本地脱敏 CSV 和 peitao 仓。正式工作流的受控 SDK 冒烟和 Platform 打包校验均已通过。正式自动修复和提交仍待验收。

工程验收还需完成 SDK 端统一 JSON Schema 和独立离线重放入口。补查前后的 SDK 账单分别保存，累计或增量口径未确认时，合计为未知。 [Agent2 调查保全与 Agent3 反馈收敛实施计划](superpowers/plans/2026-11-17-agent2-lossless-handoff-agent3-convergence-plan.md#交付检查表)

实仓和部署环境待验事项：

- 在 peitao、transport、hcp 用部署配置验证实际 SDK 工具路由的只读限制、同会话补查、逐票交接质量，以及回合和费用口径。
- 在部署环境中断调查组后重启，核对产物仍可访问、完成组可复用、中断组可续跑，以及阶段计数和原始引用可追溯。
- 用 8–12 张真实反馈票验证 Agent3 的答案消费、重复提问和补丁推进，再用至少 20 张独立标注的可修票验证补丁应用和业务回归。 [业务验收标准](superpowers/specs/2026-11-17-agent2-lossless-handoff-agent3-convergence-design.md#b-模型与真实业务验收不得由a代替)

历史样本、业务评估和交付包见[实测归档](field-eval/archive.md)。
