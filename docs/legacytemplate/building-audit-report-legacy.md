# Building Audit 报告（旧版模板，留作对照）

## 审查对象与追溯

- 功能单元：
- Reader Spec 路径及 SHA-256：
- Build Plan 路径及 SHA-256：
- 代码仓库、基线提交与待审提交：
- 审查差异包：
- 审查日期、Reviewer：
- audit_id：（绑定上述版本的唯一标识）

## 规格到实现的追溯

| Reader Spec 要求 | Build Plan 任务 | 实现位置 | 测试与冒烟证据 | 状态或缺口 |
|---|---|---|---|---|
| | | | | |

## 审查结论

- 源数据身份与资格是否按批准方案绑定：
- 概念算法、分析单位和关键科学口径是否被忠实实现：
- 跨任务接口、失败行为、复现条件与计算资源是否可靠：
- 任务 Review、未解决发现及五轮上限裁决：
- 测试和最小入口验证的实际覆盖及未验证范围：

## 问题清单

| finding_id | 严重程度 | 规格依据 | 代码或测试证据 | 影响与建议 | 返回阶段 |
|---|---|---|---|---|---|
| | blocker / major / minor | | | | Proposal / Building / none |

## 审计意见核实与已确定修复方向

初次提交报告时，本节的人工裁决均记为“待定”。用户讨论并裁决后，按 `finding_id` 逐条补充；保留上方原始发现及证据，不用改写原始意见来代替裁决。尚未决定的问题不能写成已批准的修复任务。

| finding_id | 核实结论与依据 | 用户裁决（接受／调整／不采纳／待定） | 已确定修复方向及验收证据 | 影响的 Spec／Plan 条目 | 裁决人、日期 |
|---|---|---|---|---|---|
| | | 待定 | | | |

返工 Agent 以已确定的方向实施，并在修复报告中引用 `audit_id`、`finding_id` 和修复提交；复审 Reviewer 逐条核对差异与验收证据。若裁决改变科学方案或源数据资格，返回 Proposal 并重新审批；代码修复形成新提交后，对新版本重新审查。不采纳审计意见时，记录反证与可接受的限制。

## 总体状态与用户裁决

- audit_overall_status: `BLOCKED | CHANGES_REQUIRED | PASS_WITH_NOTES | PASS`
- 非阻断遗留问题及接受后的使用限制：
- audit_user_decision: `pending`
- accepted_audit_id: `null`
- execution_authorized_by_user: `no`

报告生成后停止。用户裁决必须指向本报告及当前待审提交；修复或实质性规格变更使旧报告失效。
只有 `PASS` 或用户明确接受其非阻断遗留问题的 `PASS_WITH_NOTES` 可以申请进入 Runtime；`BLOCKED` 和 `CHANGES_REQUIRED` 必须处理后重新审查。
