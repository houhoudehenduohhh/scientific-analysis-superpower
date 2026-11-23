# Runtime Audit 报告

> 正式报告必须严格按本模板填写。Reviewer 不另行使用 Strengths、Critical/Important/Minor、Recommendations、Human Disposition 或重复的状态总览章节。报告生成后停在 Runtime Audit Gate。

## 1. 审查对象

- 功能单元及本轮审查目的：
- `audit_scope: milestone | final_chain`
- Build Plan、受审 Task MD 路径及版本：
- 已接受的 Building `audit_id` 与代码版本：
- Runtime Report 路径、节点／步骤及 `run_id`：
- 实际输入、配置、环境、日志与结果清单：
- 上游已接受节点审计 ID、版本及复用产物：
- `runtime_audit_id: <当前审计 ID>`
- `parent_runtime_audit_id: <上一份审计 ID 或 null>`
- Reviewer、审查日期：

## 2. Audit 发现的问题、解决办法及完成状态

没有发现时写“无”。每个问题必须给出证据、影响、解决办法、返回阶段和当前状态。解决办法是审计后的技术方向，不等于用户已经批准的修复。

| finding_id | 输入／日志／结果位置 | 问题及证据 | 解决办法与返回阶段（Runtime／Building／Proposal） | 状态（未开始／修复中／已复审／不成立） |
|---|---|---|---|---|
| | | | | |

每项需要返工的发现还要记录：批准依据、根因或未知、拟修改对象、受影响产物及下游节点、需要重新审查的节点或全链条范围。

## 3. 有待改进或商讨的地方

只记录不阻断当前 Runtime Audit 的限制、改进项或需要用户讨论的事项。没有则写“无”。有明确建议时写出影响和是否需要返回 Runtime、Building 或 Proposal；没有建议的事项不必列入。

| 事项 | 证据与影响 | 建议或需要用户决定的内容 |
|---|---|---|
| | | |

## 4. 未作判断的部分

列出本轮没有核实的输入、运行步骤、输出、规模、性能或科学解释，并说明原因及需要的补查。没有则写“无”。

| 未判断事项 | 原因 | 后续补查 |
|---|---|---|
| | | |

## 5. 已核实的下一步修复方向

只记录本次审计已经核实、可交给后续执行的方向。用户没有裁决的建议不能写成已批准指令。没有修复方向则写“无”。

| 方向编号 | 依据的 finding／节点／步骤 | 已核实的修复方向 | 返回阶段 | 验收证据 |
|---|---|---|---|---|
| | | | | |

## 6. 任务验收索引

第一列列出本次范围的全部 Build Task、Runtime 步骤和验收节点 ID，第三列逐项写出已批准的 AC ID、判定和验证范围。可用一行覆盖多个有直接对应关系的 ID。明确未运行、证据不足、复用的上游产物和仍待验证的部分。

| Task／步骤／节点 ID | 目的与输出 | AC、运行状态及完成边界 | 当前状态 |
|---|---|---|---|
| | | | |

## 审计门禁记录

- `runtime_audit_status: PASS | PASS_WITH_NOTES | CHANGES_REQUIRED | BLOCKED`
- `return_stage: Proposal | Building | Runtime | none`
- `limitations: []`（将接受范围内的限制写为 JSON 字符串数组，单独成行）
- `audit_user_decision: pending`
- `accepted_runtime_audit_id: null`

`PASS` 或用户接受限制的 `PASS_WITH_NOTES` 才具备提交用户裁决的条件。节点报告获接受后，按 Harness 路由进入下一节点 Proposal 或最终全链条审计。旧分批计划同一获批范围内的运行依授权衔接。最终全链条报告获接受后才可进入 Runtime Finish。新运行、代码、Spec、Plan、Task MD 或受影响结果变化会使当前报告失效，必须重新审查。
