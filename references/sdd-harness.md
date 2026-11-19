# SDD Harness

SDD 的提示词负责说明任务，Harness 负责允许或阻止状态转移。每个 Build Plan 的临时区保存一个 `state.json`。协调者派发 Agent 前后都通过 `sdd-harness.py` 检查状态。

```text
building_incomplete → task_review_pending
task_review_pending → task_complete | fix_round_pending
fix_round_pending → re_review_pending | user_decision_pending
re_review_pending → task_complete | fix_round_pending | user_decision_pending
task_complete → task_review_pending | final_review_pending
final_review_pending → building_audit_pending
building_audit_pending → building_audit_gate
building_audit_gate → runtime_authorized
```

状态转移失败时，协调者必须停在当前状态。`CHANGES_REQUIRED` 在第五轮前只能进入 `fix_round_pending`。没有修复报告、测试证据和 Re-review，不能进入 `task_complete`。没有 Final Review 不能进入 Building Audit，没有 Building Audit 不能进入 Runtime。
