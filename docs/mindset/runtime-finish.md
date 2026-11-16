# Runtime Finish 阶段大纲

**职责：**把已获用户接受的运行结果、审计证据和解释限制整理为可阅读的交付说明。

**关键边界：**核对结果与已接受的 `runtime_audit_id`、`run_hash` 一致；只解释和呈现已审结果，不新增计算或改写产物。发现新问题返回 Runtime Audit 分类。

**产物：**正式结果清单与 [Runtime Finish 交付说明](../templates/runtime-finish-report.md)，包含复现条件、可支持的结论和限制。Agent 执行规则见 [Runtime Finish 参考](../references/runtime-finish.md)。
