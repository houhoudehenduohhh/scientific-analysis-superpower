# Building 门禁检查

Building 由 SDD 负责。协调者在进入下一个状态前执行 `scripts/check-building-gate`，将失败结果写入 SDD 账本并停留在当前阶段。

## 状态转换

```text
building_incomplete → task_review_pending
task_review_pending → task_complete
全部 task_complete → final_review_pending
当前 HEAD 的 Final Review 已完成 → building_audit_pending
正式 Building Audit 生成 → building_audit_gate
登记与当前 HEAD 绑定的 Building 门禁证据 → 等用户裁决报告
Final Review 通过且用户接受通过的 Building Audit → runtime-init → 等运行授权
用户明确授权运行范围 → runtime-authorize
```

实现 Agent 未完成不能进入 Task Review。Task Review 未完成不能完成任务。Final Review 未完成不能生成正式 Building Audit。Final Review 为 `CHANGES_REQUIRED` 时，正式 Building Audit 只能为 `CHANGES_REQUIRED` 或 `BLOCKED`，提交用户裁决。Building Audit 未通过或版本绑定不一致不能进入 Runtime。

## 必查证据

当前 Build Plan、已批准 Task MD、SDD 账本、每个已执行 Task 的 brief、实现报告、提交范围、Task Review/Re-review、Final Review 和正式 Building Audit。报告必须绑定当前 Build Plan、Task MD 与代码提交身份。第 6 节逐条覆盖已批准任务与 AC，说明成功条件、判定、实际验证和未验证范围。Building gate 核对批准的主入口路径和审查基线到 HEAD 的新增脚本。

交接 Runtime 前，使用 `gate --artifact <Git工作树根目录> --evidence <Building门禁证据.json>` 登记证据。JSON 提供 `ledger`（`progress.md`）和 `tasks`（完整任务 ID 到含 `brief` 路径的对象的映射）。Harness 将这些文件与状态中已有的任务审查、整体审查和正式报告绑定。后续命令见 [Runtime Harness](sdd-harness.md#runtime-命令)。
