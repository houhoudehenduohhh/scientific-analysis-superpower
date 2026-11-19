# Building 门禁检查

Building 由 SDD 负责。协调者在进入下一个状态前执行 `scripts/check-building-gate`，将失败结果写入 SDD 账本并停留在当前阶段。

## 状态转换

```text
building_incomplete → task_review_pending
task_review_pending → task_complete
全部 task_complete → final_review_pending
Final Review 通过 → building_audit_pending
正式 Building Audit 生成 → building_audit_gate
用户接受 Building Audit → runtime_authorized
```

实现 Agent 未完成不能进入 Task Review。Task Review 未完成不能完成任务。Final Review 未完成不能生成正式 Building Audit。Building Audit 未生成或版本绑定不一致不能进入 Runtime。

## 必查证据

当前 Build Plan、Reader Spec、已批准 Task MD、SDD 账本、每个已执行 Task 的 brief、实现报告、提交范围、Task Review/Re-review、人工任务报告、Final Review 和正式 Building Audit。报告必须绑定当前 Spec、Plan、Task MD 与代码提交身份。
