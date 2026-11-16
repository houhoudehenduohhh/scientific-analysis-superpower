# Proposal 阶段

## 职责

确定研究问题、数据身份、分析逻辑、科学边界和实现方向，让人能够理解并批准后续工作。

## 核心思考

- 研究对象和分析单位是什么；
- 使用的源数据是否正确、合格、可追溯；
- 数据如何经过处理形成分析样本；
- 统计或算法方案为什么适合当前问题；
- 哪些结论可以支持，哪些结论不能支持；
- 哪些内容仍需要用户决定。

## 主要产物

- `reader_spec.md` 记录整体逻辑、概念算法、科学依据及验收边界。
- `build_plan.md` 记录工程实现、文件结构、任务和验证计划。

具体操作见 [Proposal 阶段规则](../references/spec-stage.md)：先用 `brainstorming` 形成 Reader Spec，再用 `writing-plans` 形成 Build Plan；两份当前文件一起审批。

## 门禁

两份文件均完成，源数据身份及资格明确，关键歧义已解决，并获得用户明确批准后，才能进入 Building。

Proposal 不生成生产代码，不运行正式分析，不生成 Audit 裁决。

## 功能单元初始化

Proposal 开始时确定一个最小功能单元，并初始化：

```text
specs/
scripts/build/
scripts/config/
scripts/pytest/
scripts/smoke_test/
scripts/logs/
results/data/
results/plot/
results/smoke_test/
reports/
audits/building/
audits/runtime/
```

其中 `specs/`、`reports/` 和 `audits/` 只存放 Markdown。目录初始化不等于内容批准，仍需完成 Proposal Gate。

## Proposal 执行顺序

1. 确定最小功能单元、源数据身份和资格；
2. 编写 Reader Spec，明确整体逻辑、概念算法、科学假设和验收条件。
3. 编写 Build Plan，先规划实现、文件和接口，再拆分可独立验收的任务。
4. 检查每项关键要求是否有对应任务和验证方法。
5. 两份文件标记为 `draft`，提交用户审批。
