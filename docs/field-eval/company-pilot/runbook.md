# Claude Code 执行手册

记录工具提交号、业务仓 HEAD、仓型、模型、skill 目录和独立产物目录。安装公司环境可用的 Claude Code CLI，并从工具仓根目录安装依赖。模型和 SDK 环境配置见 [项目 README](../../../README.md)。先用一张定位明确的票实测 Agent2 和 Agent3 的 SDK，截图票另核实模型实际读取了图片。

以下占位符按实际值替换。先创建产物目录，放在业务仓外。首轮确认 BUGFIX_APPLY_FIX 未开启。

```text
python -m pip install -e ".[agent1,platform,sdk]"
bugfix-agent preflight --source "<原始缺陷.csv>"
bugfix-agent prepare-batch --source "<原始缺陷.csv>" --product-line "<产品线>" --posture alpha --out "<产物目录>/agent1-defect-batch.json"
bugfix-platform run --work-dir "<业务仓根目录>" --product-line "<产品线>" --defect-batch "<产物目录>/agent1-defect-batch.json" --posture alpha --cartography-profile "<实际仓型>" --cartography-mode sdk --analyze-mode sdk --out-dir "<产物目录>"
```

仓型取 electron_node、micro_frontend、device_web 或 unknown。有试点业务 skill 时加 --skills-dir。

## 可直接交给公司 Claude Code 的指令

> 依次执行本手册的 Agent1 和 Platform 正式命令。首轮只出报告。保存每条命令的退出码、stdout/stderr 和完整产物目录。核对票数、排除原因、实际 SDK 来源和逐票结论。按票记录回退、预算中断、附件未读或产物缺失。保留原始产物供人工验收。

## 反馈和修复验收

填写本轮生成的反馈表，再执行以下命令。先验证反馈消费。只有选定需要改码的票才执行带 --apply-fix 的续跑。

```text
bugfix-platform feedback --root "<产物目录>" --file "<已填写反馈表>"
bugfix-platform resume --root "<产物目录>" --defect-id "<票号>" --execute
bugfix-platform resume --root "<产物目录>" --defect-id "<票号>" --apply-fix
```

用户应用并验收候选补丁，暂存该票的变更，再执行 bugfix-platform commit --root "<产物目录>" --defect-id "<票号>"。命令使用模型生成的提交信息创建本地提交。
