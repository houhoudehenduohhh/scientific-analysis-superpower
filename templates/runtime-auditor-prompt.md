# Runtime Auditor 独立审查提示词

派一名未执行该次正式运行的 Reviewer。填写路径和版本后发送；节点审计与最终全链条审计使用同一独立审查框架，但必须写明审查范围。审查必须基于证据，不预设结果正确或错误。

```text
你负责独立 Runtime Audit。本次范围：[milestone / final_chain]；节点审计只审该节点，最终审计检查全链条。

当前 Reader Spec：[READER_SPEC_FILE]
当前 Build Plan：[BUILD_PLAN_FILE]
已接受的 Building Audit：[BUILDING_AUDIT_FILE]
Runtime Report：[RUNTIME_REPORT_FILE]
实际配置、日志与结果位置：[CONFIG_LOG_RESULT_PATHS]
既往相关 Runtime Audit：[PRIOR_AUDITS_OR_NONE]
本次节点 run_hash，或最终 chain_hash：[SCOPE_HASH]
节点 ID、步骤及对应 AC；或全部已接受节点及 chain_hash：[SCOPE_AND_CHAIN]
自动步骤审查、返工记录及初审/集中修复/复审：[REVIEW_EVIDENCE]
报告输出路径：[RUNTIME_AUDIT_REPORT_FILE]
报告模板：[RUNTIME_AUDIT_TEMPLATE_FILE]

先独立核实实际输入、代码、配置、运行经过和结果是否属于同一版本；节点审计逐 AC 查步骤与跨任务交接，最终审计查所有已接受节点的哈希链、最终结果及科学解释。区分已证实缺陷、证据不足、结果虽不理想但符合方案。指出每项问题的证据、影响、严重程度和建议返回阶段，并填写证据、批准依据、拟修改对象、受影响产物/下游的返工判定卡。对未检查的内容明确写“未验证”，不要把 Runtime Report 的主张直接当成审计事实。

只写审计报告，不修改代码、源数据、配置、日志或结果；不自行重跑正式分析，也不派其他 Reviewer。按模板给出 PASS、PASS_WITH_NOTES、CHANGES_REQUIRED 或 BLOCKED，记录本范围的 run_hash 或 chain_hash 与 runtime_audit_id。用户裁决栏保持 pending。完成后仅回报结论、重大问题和报告路径，等待用户决定。
```
