---
name: scientific-analysis-superpower
description: Use to prepare and approve the Reader Spec and Build Plan for one scientific-analysis functional unit before implementation.
---

# Scientific Analysis: Proposal

本模块只负责 Proposal。先读 [阶段规则](references/spec-stage.md)，再按其顺序调用 [brainstorming](skills/brainstorming/SKILL.md) 和 [writing-plans](skills/writing-plans/SKILL.md)。两份文档的栏目分别见 [Reader Spec 模板](templates/reader-spec.md) 和 [Build Plan 模板](templates/build-plan.md)。

每个最小功能单元的 `specs/` 中只交付当前 `reader_spec.md` 与 `build_plan.md`。确认源数据身份与资格；按需只读探查，不静默替换输入。两份文档原位迭代，须一起提交用户明确批准。批准前不得开始 Building、正式运行或独立代码审计。Builder check 只用于修订 Reader Spec，不产生第三份正式 Proposal 文件。

[Proposal 大纲](docs/proposal.md)供人工审阅。`scripts/profile_data.py` 是可选的数据概况工具，其描述性输出不能替代研究判断。
