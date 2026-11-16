# Runtime Audit 阶段大纲

**职责：**一名未负责该次运行的独立 Reviewer 核对运行身份、完整性、正式结果与科学解释边界。

**关键边界：**Runtime Report 是审查输入，不是审查结论。结果“不理想”先分类：运行条件问题返回 Runtime；实现问题返回 Building 并重过 Building Audit；科学方案或数据资格问题返回 Proposal。无已证实缺陷但有非阻断限制时，交用户决定是否接受。

**产物与门禁：**与单一 `run_hash` 绑定的 [Runtime Audit 报告](../templates/runtime-audit-report.md)。独立报告生成后停止；用户接受当前报告前不能进入 Runtime Finish。Agent 审查规则见 [Runtime Audit 参考](../references/runtime-audit.md)。
