# Building Audit 报告模板

> 本模板沿用 Superpowers `requesting-code-review/code-reviewer.md` 的 **Strengths → Issues（Critical / Important / Minor）→ Recommendations → Assessment** 顺序；科研溯源、用户裁决和 Runtime 门禁是本项目增补。仅在整体初审和至多一次自动修复／复审结束后生成正式报告；初审记录留在 SDD 临时工作区，不使用本模板的 `audit_id`。

## Review Context · 审查对象

- 功能单元及实现摘要：
- Reader Spec 路径、SHA-256、批准状态：
- Build Plan 路径、SHA-256、批准状态：
- 代码仓库、基线提交 `BASE`、待审提交 `HEAD`：
- 完整差异包及范围 `BASE..HEAD`：
- 合格源数据的身份、版本及资格证据：
- 任务 Review 与 Re-review 记录、未关闭问题：
- 适用的 pytest、语法/导入和真实小样本 smoke test 证据：
- Reviewer、审查日期、`audit_id`：
- 上一轮审计 `parent_audit_id`（首次写“无”）：

## Strengths · 已确认的优点

写出可定位的具体优点及证据；没有充分证据则写“未确认”，不写笼统赞语。

- 

## Issues · 发现的问题

每条发现给出稳定的 `finding_id`、代码位置、规格依据或合理使用预期、可核实的证据、影响及建议。区分实现缺陷与 Spec/Plan 本身的缺陷。问题等级按实际影响判断。

### Critical · 必须修复

例如会使目标输出错误、数据丢失、源数据资格失效或正式运行不安全的问题。

- `finding_id`：
  - 文件与行号／受影响结果：
  - 问题及证据：
  - 违反的 Reader Spec、Build Plan 条目或适用预期：
  - 影响与建议方向：
  - 建议返回：Proposal / Building / 无：

### Important · 应修复

例如关键功能缺失、架构或错误处理缺陷、重要测试空白、规模与性能明显不满足已批准运行目标。

- `finding_id`：
  - 文件与行号／受影响结果：
  - 问题及证据：
  - 影响与建议方向：
  - 建议返回：Proposal / Building / 无：

### Minor · 可讨论的改进

例如不改变当前科学结论和正式运行资格的局部维护性、文档或可选性能改进；若影响可信度，不应列为 Minor。

- `finding_id`：
  - 文件与行号／受影响结果：
  - 问题及证据：
  - 影响与建议方向：

## Recommendations · 审查建议

归纳代码质量、测试、架构、复现与资源方面的建议。这里仍是 Reviewer 的建议，**不是**已获批准的修复指令。

- 

## Declined to Judge · 未作判断的事项

逐条说明无法判断的行为或证据及原因，并指出需要哪项补查；没有则写“无”。不得把尚未核实的重大问题静默排除。

- 

## Assessment · 审查结论

原版的 `Ready to merge? Yes / No / With fixes` 在科研流程中对应**是否具备提交 Building Audit 用户裁决的条件**，不直接授权合并或 Runtime。

- 总体结论：`PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED`
- 理由：
- Reader Spec 要求 → Build Plan 任务 → 实现 → 测试/冒烟证据的主要追溯结论：
- 源数据资格、算法口径、跨任务接口、失败行为、复现条件与性能预算的核查结论：
- 已执行的命令、量化结果、对应提交及未验证范围：
- 非阻断遗留问题与接受后的使用限制：

## Human Disposition · 用户核实与已确定修复方向

初审时逐项记“待定”。用户在对话中明确裁决后，由协调 Agent 按原话及证据在同一 `finding_id` 下补充决定，保留上文 Reviewer 原始问题与建议，不以改写原文代替裁决；不清楚的决定仍记“待定”。

| finding_id | 用户核实与依据 | 裁决：接受／调整／不采纳／待定 | 已确定修复方向与验收证据 | 影响的 Spec／Plan | 裁决人及日期 |
|---|---|---|---|---|---|
| | | 待定 | | | |

## 当前审计状态总览 · 决策与实施时点

本节在原始发现和逐条裁决之后更新，按 `finding_id` 或可追溯事项归类；审查发现对应审查当时的版本，后续用户决定以本节及上方裁决表为现行处理依据。**“已确定”只表示处理方向明确，不表示已经修复、验证或接受本次审计。**未获用户确认的 Reviewer 建议仍属待裁决。每项写清本轮动作或暂缓理由、实施状态与下一次复查条件；没有同类事项写“无”。

| 决策状态 | `finding_id`／事项 | 决定依据或待决问题 | 本轮动作／暂缓理由 | 实施与验证状态 | 下一步及复查条件 |
|---|---|---|---|---|---|
| 已确定，当前需处理 | | | | 未开始／进行中／已验证 | |
| 仍未确定，需讨论 | | | | 未开始 | |
| 本轮暂缓／跳过 | | | | 不适用／未开始 | |
| 已确定，后续阶段处理 | | | | 未开始 | |

“本轮暂缓／跳过”须说明用户裁决或适用范围、潜在影响及重新纳入的触发条件；不能借此排除影响本次可信度或门禁的未解决问题。问题的严重程度、实施状态与用户是否接受审计分别记录，不以本表替代 Assessment 或门禁字段。

- `audit_user_decision: pending`
- `accepted_audit_id: null`
- `execution_authorized_by_user: no`

报告提交后停在用户门禁。用户决定须对应当前 Spec、Plan 和代码提交；修复代码或实质性改动规格后，旧报告不能授权新版本运行，须重新审查。只有当前版本 `PASS`，或用户明确接受限制的 `PASS_WITH_NOTES`，才可申请进入 Runtime。
