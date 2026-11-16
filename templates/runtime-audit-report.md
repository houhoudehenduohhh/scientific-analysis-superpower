# Runtime Audit 报告

## 审查对象与追溯

- 功能单元、审查日期、独立 Reviewer：
- Reader Spec、Build Plan 路径及指纹：
- 已接受的 Building `audit_id` 与代码提交：
- Runtime Report 路径、`run_id`、`run_hash`：
- 实际输入、配置、环境、日志与结果清单：
- `runtime_audit_id`、`parent_runtime_audit_id`（首次写“无”）：

## Strengths · 经证据支持的结论

- 

## Issues · 发现的问题

每条记录 `finding_id`、严重程度、规格或结果契约、输入/日志/结果证据、影响及建议返回阶段。没有问题写“无”；不把结果不符合预期直接写成缺陷。

### Critical · 阻断

- `finding_id`、证据、影响、建议返回：Proposal / Building / Runtime：

### Important · 需处理

- `finding_id`、证据、影响、建议返回：Proposal / Building / Runtime：

### Minor · 非阻断限制

- `finding_id`、证据、影响与使用限制：

## Recommendations · 审计建议

- 对每个已证实问题建议核实或修复方向；建议尚不是用户批准的返工任务。

## Declined to Judge · 未验证范围

- 未能检查的输入、运行步骤、输出或科学判断及原因；需要的补充证据：

## Assessment · 独立结论

- `runtime_audit_status: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED`
- 核对 `run_hash`、输入、代码、配置和结果一一对应的证据：
- 运行完整性、输出 schema/数量/缺失/数值边界及适用诊断的结论：
- 解释边界与非阻断限制：
- `return_stage: Proposal | Building | Runtime | none`
- 判断依据与不能据此推断的内容：

## Human Disposition · 用户核实与已确定方向

初审时逐项记“待定”。用户在对话中明确裁决后，由协调 Agent 按 `finding_id` 记录决定及依据，保留原始 Reviewer 发现；不清楚的决定仍记“待定”。旧报告只代表旧 `run_hash`。

| finding_id | 核实依据 | 接受／调整／不采纳／待定 | 已确定处理方向与验收证据 | 裁决人及日期 |
|---|---|---|---|---|
| | | 待定 | | |

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
- `accepted_runtime_audit_id: null`
- `accepted_run_hash: null`

报告生成后停止。只有用户在看到本报告后明确接受当前 `runtime_audit_id` 与 `run_hash`，且结论为 `PASS` 或获用户接受限制的 `PASS_WITH_NOTES`，才能进入 Runtime Finish。
