# Building Audit 阶段

## 职责

审查代码是否忠实实现批准的 Spec，并判断是否具备正式运行条件。

## 审查层次

### 任务级 Review

检查单个任务是否完成、测试是否真实有效、接口是否兼容、是否出现过度实现或未批准的科学决策。

### Build 总审计

由一名独立 Reviewer 检查完整代码的数据流、模块接口、断言、错误处理、依赖、复现条件和高风险边界测试，并形成一份可追溯报告。

任务级 Review 只审查单个 task brief 及其 diff，不读取完整项目 Specs；Build 总审计才检查当前 Reader Spec、Build Plan、完整代码和任务 Review 汇总之间的一致性。

## 主要产物

- 一份按 [Building Audit 模板](../templates/building-audit-report.md)生成的正式报告；
- 任务级 Review 汇总；
- `Issues` 中的阻断问题，以及用户讨论后写入 `Human Disposition` 的已确定修复方向；
- `build_audit_id` 与用户裁决状态。

审计文件按阶段、序号、日期和哈希命名，例如：

```text
audits/building/001_20261111_audit_<audit_hash>.md
```

每次审计至少记录 `audit_id`、Reader Spec 与 Build Plan 的指纹、代码提交和审查差异；返工后再审计时记录上一轮 `audit_id`。已确定的修复方向在本次正式报告中按 `finding_id` 对应，不另起一份必需的修复计划。Building Audit 同时读取当前 Reader Spec、Build Plan、代码、测试和既往 Building Audit。

## 门禁

Building Audit 报告生成后必须停止，等待用户接受。通过 Building Audit 只表示代码可以进入正式运行，不表示运行结果已经可信。
