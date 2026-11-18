# Proposal 阶段

## 目标与输出

在功能单元的 `specs/` 下只交付两个当前 Markdown 文件：[Reader Spec](../templates/reader-spec.md)（`reader_spec.md`）和 [Build Plan](../templates/build-plan.md)（`build_plan.md`）。两份文件一起提交给用户审批。此阶段只做规划和必要的只读探查。代码、测试实现和独立审计由后续阶段产出。

## Proposal 执行顺序

开始 Proposal 前，按[阶段模型规则](model-selection.md)为主会话选择推理档位。

1. 确定最小功能单元和写入位置，按 [brainstorming](../skills/brainstorming/SKILL.md) 先阅读项目约定、既有规格和源数据证据，再澄清会改变方案的事项。对迁移中的项目，可从旧规格提取已确认决定，新文件仍需按当前门禁批准。
2. 确认源数据的确切身份、版本、来源、覆盖范围、结构与资格证据。区分已确认事实、候选方案和待确认事项。只询问会实质影响方案、实现或写入位置的问题。
3. 先按 [Reader Spec 模板](../templates/reader-spec.md) 写 `reader_spec.md`。明确目标、分析单位、概念算法、关键口径、适用的统计假设和质量风险、科学验收条件及结论边界。项目规模需要时，按 [builder check](../skills/brainstorming/builder-check-prompt.md) 独立检查实质缺口，修订当前文件；检查不产出第三份正式文档。
4. 再按 [writing-plans](../skills/writing-plans/SKILL.md) 的文件职责、任务粒度及自检方法，用 [Build Plan 模板](../templates/build-plan.md) 写 `build_plan.md`。先梳理工程实现路线、拟修改的文件及接口，再按可独立测试和验收的行为切分任务。逐任务写明目的、边界、带稳定编号的验收条件及其预定验证阶段，再明确依赖、测试断言、命令和预期结果。用户应能在 Proposal 审查每个 Task 的成功标准。按实际规模确定资源与效率安排。
5. 检查 Reader Spec 的关键要求是否都有实现任务和验证证据的预定落点，任务之间的接口、依赖和命令是否一致；再检查 Runtime 步骤图无环、前置产物与并行写入不冲突、每项 Runtime AC 落在一个阶段性验收节点。用户在此阶段审阅节点范围与顺序；实质歧义回到对应文档解决。
6. 原位更新两份当前文件并标记 `status: draft`，报告待确认事项和文件路径，停止等待用户对当前两份文件的明确批准。

## 数据检查

Read-only schema and quality inspection is allowed when the user has placed the data in scope. The optional `scripts/profile_data.py` reports descriptive facts. Its output is evidence, not a treatment decision.

Do not turn a distribution shape, missingness percentage, diagnostic test, or software default into an automatic modeling choice. Explain candidate responses and record the selected response only after reasoning from the scientific context.

## 门禁

源数据身份及资格明确、实质歧义解决、用户明确批准当前两份文件后，才能进入 Building。原有规格的批准不能直接沿用到重写的文件。
