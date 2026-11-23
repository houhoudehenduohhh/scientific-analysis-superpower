# Building Audit 报告

> 正式报告必须严格按本模板填写。Reviewer 不另行使用 Strengths、Critical/Important/Minor、Recommendations、Human Disposition 或重复的状态总览章节。报告生成后停在 Building Audit Gate。

## 1. 审查对象

- 功能单元及本轮审查目的：
- Build Plan 路径及批准状态：
- 受审 Task MD、完整任务 ID 及批准状态：
- 代码仓库、基线和受审版本说明：
- 源数据身份、资格证据、任务 Review/Re-review、测试和 smoke 证据：
- Reviewer、审查日期：
- `audit_id: <当前审计 ID>`
- `parent_audit_id: <上一份审计 ID 或 null>`

## 2. Audit 发现的问题、解决办法及完成状态

没有发现时写“无”。每个问题必须给出证据、影响、解决办法、返回阶段和当前状态。解决办法是审计后的技术方向，不等于用户已经批准的修复。

| finding_id | 文件／结果位置 | 问题及证据 | 解决办法与返回阶段 | 状态（未开始／修复中／已复审／不成立） |
|---|---|---|---|---|
| | | | | |

## 3. 有待改进或商讨的地方

只记录不阻断当前 Building Audit 的改进项或需要用户讨论的事项。没有则写“无”。有明确修复建议时，写出建议、影响和是否需要返回 Proposal／Building；没有建议的事项不必列入。

| 事项 | 证据与影响 | 建议或需要用户决定的内容 |
|---|---|---|
| | | |

## 4. 未作判断的部分

列出本轮没有核实的行为、数据、规模、环境或结果，并说明原因及需要的补查。没有则写“无”。

| 未判断事项 | 原因 | 后续补查 |
|---|---|---|
| | | |

## 5. 已核实的下一步修复方向

只记录本次审计已经核实、可交给后续执行的方向。需要修复时返回 Building，涉及科学方案、源数据资格或目标量时返回 Proposal。没有修复方向则写“无”。用户没有裁决的建议不能写成已批准指令。

| 方向编号 | 依据的 finding／Task／AC | 已核实的修复方向 | 返回阶段 | 验收证据 |
|---|---|---|---|---|
| | | | | |

## 6. 任务验收索引

在第一节写明当前节点和获批 Task 范围。旧分批计划写明本批及覆盖节点。逐条列出本次建设范围内所有获批任务和扩展任务的 AC。沿用 Task MD 的完整 ID、任务目的和成功条件。完成情况写明当前判定、实际验证的行为与未验证范围。需要说明返工时，简述受影响的 AC 和复审结论。未运行、证据不足或需等 Runtime 验证的条件逐条标明。

| 任务 ID | 任务目的 | AC ID | 成功条件 | 完成情况与验证范围 |
|---|---|---|---|---|
| | | | | |

## 审计门禁记录

- `assessment: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED`
- `limitations: []`（填写用户需接受的限制，使用 JSON 字符串数组）
- `audit_user_decision: pending`
- `accepted_audit_id: null`
- `execution_authorized_by_user: no`

`PASS` 可提交用户验收，`PASS_WITH_NOTES` 须由用户一并接受所列限制。`CHANGES_REQUIRED` 或 `BLOCKED` 须提交用户裁决后续处置。用户接受后，代码、Spec、Plan 或 Task MD 变化会使当前报告失效，必须重新审查。此报告不替代 Runtime Audit，也不直接授权 Runtime。
