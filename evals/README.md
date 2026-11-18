# 离线评测

- Agent2 使用 `python evals/eval_agent2.py --repo <repo> --profile <profile> --batch <defect-batch.json> --cases <cases.json>`。
- Agent3 使用 `python evals/eval_agent3.py --report <analysis-report.json> --cases <cases.json>`。评分口径、人工模板与实仓验收方式见 [Agent3 实仓评测](../docs/field-eval/agent3/README.md)。
- 可共用的微型仓和缺陷输入位于 [工程夹具](../tests/fixtures/)。
