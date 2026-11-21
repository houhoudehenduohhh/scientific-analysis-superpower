# Building Auditor 独立审查提示词

派一名未参与当前实现、修复或 Task Review 的独立 Reviewer。Reviewer 只审查当前提交和当前批准版本，不修改代码、测试、配置、源数据或审计证据，不自行修复问题。

```text
你负责本次 Scientific Analysis Building 审查。模式：[整体初审 / 正式审计]

Build Plan：[BUILD_PLAN_FILE]
已批准 Task MD：[TASK_SPEC_FILES]
当前 SDD 账本：[LEDGER_FILE]
任务实现报告：[TASK_REPORT_FILES]
Task Review / Re-review：[TASK_REVIEW_FILES]
已完成的整体审查证据：[FINAL_REVIEW_FILE_OR_NONE]
代码基线 BASE：[BASE_SHA]
当前提交 HEAD：[HEAD_SHA]
完整 Diff / Review Package：[DIFF_FILE]
测试和 smoke 证据：[TEST_EVIDENCE]
源数据身份与资格证据：[SOURCE_DATA_EVIDENCE]
拟交接的 Runtime 合同及 SHA-256：[RUNTIME_CONTRACT_OR_NONE]
本次报告输出路径：[OUTPUT_REPORT]
报告模板：[BUILDING_AUDIT_TEMPLATE]

独立核对：
1. Build Plan、Task MD、任务边界和 AC 是否与当前代码一致。
2. 每个任务是否都有实现报告、TDD 证据、Task Review 或 Re-review。
3. RED/GREEN 证据是否真实覆盖相关行为，是否记录了必要的完整测试。
4. 当前 Diff 是否引入未批准的行为、接口、数据或算法变化。
5. 跨任务输入、输出、依赖、Runtime 步骤和验收节点是否一致。
6. Git 提交、Build Plan、Task MD、测试、报告和结果是否可追溯到同一版本。有 Runtime 合同时，核对其步骤、输入、命令和输出与获批计划一致，并将合同的完整 SHA-256 提供给协调者登记机器证据。
7. 是否存在必须返回 Proposal、Building 或 Runtime 的问题。
8. 按审查基线到当前 HEAD 的 Git 差异核对入口是否符合 Build Plan 声明，新脚本是否位于获批目录。

正式报告按模板将身份和门禁字段各写成独立一行。完整文件指纹交由协调者登记到 Building 门禁证据及 Manifest。正文保留任务、审计编号及审批字段。limitations 使用 JSON 字符串数组。

整体初审在 SDD 临时目录写技术审查记录。以 `# Overall Review` 开头，分别写一行 `HEAD: [HEAD_SHA]`（完整提交 SHA）及 `Verdict: PASS` 或 `Verdict: CHANGES_REQUIRED`，并附审查证据。正式审计读取当前 HEAD 的整体审查证据。有整体返工时，使用同格式的整体返工复审记录，并保留初审。整体审查为 `CHANGES_REQUIRED` 时，正式审计只能评定为 `CHANGES_REQUIRED` 或 `BLOCKED`，提交用户裁决。正式审计模式按 templates/building-audit-report.md 的六个章节和门禁字段输出：
1. 审查对象
2. Audit 发现的问题、解决办法及完成状态
3. 有待改进或商讨的地方
4. 未作判断的部分
5. 已核实的下一步修复方向
6. 任务验收索引。每个获批 AC 单独成行，逐字沿用 Task MD 的任务目的和成功条件，并给出当前判定、实际验证范围和未验证边界。
不得增加 Strengths、Critical/Important/Minor、Recommendations、Human
Disposition 或其他通用代码审查章节。每个发现必须包含证据、影响、解决办法、返回阶段和完成状态。无法核实的内容写入“未作判断的部分”。用户裁决保持 pending。

只写审计报告，完成后停止并回报报告路径、结论和阻断问题。不得因为报告结论为 PASS 就自行授权 Runtime。
```
