# Fix loop 状态门禁

审查发现问题后，协调者必须记录结构化状态：

```text
task_review_status = CHANGES_REQUIRED
fix_round = 1..5
fix_dispatch = pending | complete
fix_report = pending | present
re_review = pending | ADDRESSED | NOT_ADDRESSED
```

`CHANGES_REQUIRED` 或 Critical/Important finding 在 `fix_round < 5` 时，只允许继续当前任务的修复循环。没有修复报告、覆盖测试、修复差异和 Re-review，不能把任务标记完成，也不能推进其他阶段。第五轮仍有未关闭问题时才进入用户裁决状态。
