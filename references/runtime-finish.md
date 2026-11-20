# Runtime Finish：已审结果交付

进入前核对 Build Plan 的全部 Runtime 验收节点各有对应当前版本的已接受审计，且最终全链条 Runtime Audit 为 `PASS` 或用户明确接受限制的 `PASS_WITH_NOTES`；`audit_user_decision=accepted`、`accepted_runtime_audit_id=runtime_audit_id`、`accepted_chain_hash=chain_hash`，且结果文件仍与该审计所列的清单一致。上述条件都是阻塞式判断；任一受影响版本或文件已变更，停止并返回所属阶段，不能沿用旧批准。

按 [Runtime Finish 模板](../templates/runtime-finish-report.md)在 `reports/` 生成中文 Markdown 交付说明，例如 `reports/runtime_finish_<sequence>_<date>.md`。正文包含「阶段性结果」和「结果局限」两节，说明本轮完成情况、所得结果及结论范围，必要时链接 `results/data/`、`results/plot/` 或 `results/smoke_test/` 的已发布文件。Harness 在 Manifest 留存最终审计身份、逐文件指纹与结果清单。早期已绑定运行按原模板完成。

本阶段不新增计算、不改模型、不修复代码、不重跑、不改写正式数据或图件。若整理时发现结果不完整或解释冲突，暂停交付并返回 Runtime Audit 分类。临时预览、PID 和进度状态不进入交付清单；临时 SDD 工作区留存供 Agent 复查与恢复。

使用 Harness `runtime-finish` 登记当前交付说明和最终验收证据。命令成功后再报告交付完成。
