# Building 阶段：科研边界

本文件只说明原版 [subagent-driven-development](../skills/subagent-driven-development/SKILL.md) 在科研功能单元中的适用边界；任务派发、提示词、取证命令、返工及恢复仍由该 Skill 定义。

## 前置与工作区

- 当前 `reader_spec.md` 与 `build_plan.md` 已获用户明确批准，源数据身份及资格已确定。方案或数据口径发生实质变化时返回 Proposal；Build Plan 的实质变更先交用户确认。
- 在已确定的最小功能单元内核对 `specs/`、`scripts/`、`results/`、`reports/`、`audits/` 的职责边界；按已批准计划建立本阶段实际需要的 `scripts/build/`、`scripts/config/`、`scripts/pytest/`、`scripts/smoke_test/`、`scripts/logs/`、`results/smoke_test/`、`audits/building/`。`reports/` 与 `audits/` 只放 Markdown 正式文档，不为追求目录齐全创建空占位文件。
- 在有首个提交的 Git 工作树中执行。每个任务开始前记录 `BASE`，实现和修复各自提交，再以对应 `BASE..HEAD` 生成审查差异。派审前检查未提交改动，避免遗漏待审代码。提交只固定待审版本，不代表任务通过。
- `review-package` 要求工作树干净。冒烟产物应按项目约定明确纳入版本控制或排除在 Git 状态之外；报告仍记录输入、命令、产物路径与必要指纹，不能仅为通过干净检查而丢弃审计证据。
- 实现和审查使用获批准计划的单任务 brief、报告和差异；Task Reviewer 只获取该任务适用的科学约束。完整 Reader Spec、Build Plan 与跨任务数据流留给最终 Reviewer。
- SDD 进度账本、brief、任务报告和审查包放在当前功能单元的临时工作区。未完成的返工保留以便恢复。临时材料的保留与删除条件尚待用户裁定；裁定前不得自动清理。

## 测试与运行边界

- 按 [TDD](../skills/test-driven-development/SKILL.md) 和 [Writing Good Tests](../skills/test-driven-development/writing-good-tests.md) 完成适用的行为测试。期望值应来自独立依据；需要时使用手算夹具、性质测试、合成输入或获准的小规模真实样本。
- 任务内执行定向测试，交付前执行适用的全套测试。完成所有任务后执行适用的语法、导入、静态检查和最小入口冒烟测试，并记录命令、输出、输入身份和对应提交。
- Building 不对预定正式源数据运行主生产分析，也不产出正式科研结果。测试通过不等于科学结果可信。

## 返工与门禁

- 每个任务必须得到独立 Reviewer 对契约符合性和代码质量的双重结论。修复后使用局部差异复审。按原版上限最多五轮；仍有实质缺陷时暂停自动开发，带完整证据交用户决定。非阻断问题可以如实列入最终报告，由用户决定是否接受。
- 全部任务结束后，按 [最终 Review 规则](../skills/subagent-driven-development/references/final-review.md)交一名独立 Reviewer 审查完整分支，形成一份 [Building Audit 报告](../templates/building-audit-report.md)。报告关联当前 Spec、Plan、代码提交、任务审查和最小验证证据。用户接受前不得进入 Runtime。
