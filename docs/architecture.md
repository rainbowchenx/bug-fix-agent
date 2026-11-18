# 当前项目架构

Agent1 独立导入和整理缺陷并输出 `DefectBatch`。Platform 消费这份产物，通过 Agent2 调查代码并通过 Agent3 交付报告。Pydantic 契约位于 `contracts/bugfix_contracts/`。

## 三条正式链路

- **首跑**由 CLI 或 HTTP 调用 `workflow/run.py` 的 `run_three_agent_workflow`。LangGraph 部署复用 `workflow/graph.py` 的同一张图。图校验输入和 Agent 产物，并调用统一报告发布。
- **调查交接**由 `agents/cartographer/run.py` 调度。分组、重跑和预算进度在 `investigation.py`。SDK 捕获执行和响应，`handoff.py` 决定怎样保留、校验和合并逐票结果。
- **反馈和续跑**由 `workflow/resume.py` 接收。它持有产物锁，导入反馈或确定续接方式和父轮。首跑和续跑都通过 `agents/analyst/run.py` 调用 `attempt.py` 的逐票尝试。逐票流程决定编辑资格、验证和当轮状态。

## 状态和恢复

- LangGraph checkpoint 保存批次编排位置，Claude SDK session 提供可选的对话续接。
- 已提交的逐票 attempt、分析快照及 latest 指针保存业务进展。汇总损坏后由 `agents/analyst/report_store.py` 从已提交快照恢复。
- 报告 JSON 和 Markdown 通过共享发布路径写出。首跑与续跑在同一产物根内使用同一排他锁协调逐票提交和汇总发布。
- 用户自己应用和验收补丁。报告默认不编辑，续跑使用显式授权开启编辑。

工程回归在 `tests/`，共用夹具在 `tests/fixtures/`。依赖方向由 `tests/test_package_boundaries.py` 检查。离线评分见 [evals](../evals/README.md)，构建入口为 `python packaging/build.py`。
