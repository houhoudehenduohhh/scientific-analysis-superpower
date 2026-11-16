# Runtime Finish：已审结果交付

进入前核对当前 Runtime Audit 为 `PASS` 或用户明确接受限制的 `PASS_WITH_NOTES`；`audit_user_decision=accepted`、`accepted_runtime_audit_id=runtime_audit_id`、`accepted_run_hash=run_hash`，且结果文件仍与该审计所列的清单一致。上述条件都是阻塞式判断；任一版本或文件已变更，停止并返回所属阶段，不能沿用旧批准。

只整理本次已审的 `results/data/`、`results/plot/` 和必要的日志、配置及报告。按 [Runtime Finish 模板](../templates/runtime-finish-report.md)在 `reports/` 生成中文 Markdown 交付说明，例如 `reports/runtime_finish_<run_hash前12位>.md`，说明每项结果回答的问题、所依赖的源数据/代码/配置/运行/审计、可支持的结论、限制与未解决事项。图件和表格可作阅读友好的嵌入或链接；版式重要时检查实际文件。

本阶段不新增计算、不改模型、不修复代码、不重跑、不改写正式数据或图件。若整理时发现结果不完整或解释冲突，暂停交付并返回 Runtime Audit 分类。临时预览、PID 和进度状态不进入交付清单；临时 SDD 材料按尚待用户裁定的保留规则处理，不能在此阶段自行删除。
