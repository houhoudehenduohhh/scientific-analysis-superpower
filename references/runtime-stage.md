# Runtime：正式运行

本阶段只执行已批准的科研功能单元，形成事实性的 Runtime Report；不自行审计结果或宣布结果可交付。

## 入口门禁

在**每次正式运行前**核对并记录：

1. 当前 `reader_spec.md` 和 `build_plan.md` 已获批准，源数据身份、资格与目标输出仍适用；
2. Building Audit 的结论为 `PASS`，或用户已明确接受 `PASS_WITH_NOTES` 的限制；`audit_user_decision=accepted`、`accepted_audit_id=audit_id`，且用户在看到这份报告后的后续消息明确授权运行；
3. 待运行的代码提交与该 Building Audit 审查的 `HEAD` 一致；受审代码、依赖或会改变计算语义的配置若已变更，先返回 Building；
4. 实际输入与 Reader Spec 的批准身份、版本和资格相符；写入目录、命令及预计资源在获批范围内。

任一条件缺失、矛盾或无法核实，停止并报告缺口。不得从“批准 Spec”“继续”或较早的运行许可推断当前版本已获放行。

正式入口前必须逐项作阻塞式判断，任何一项为假或未知都不能启动命令：

```text
assert spec_and_plan_approved_for_current_versions
assert building_audit_status in {PASS, user_accepted_PASS_WITH_NOTES}
assert audit_user_decision == accepted
assert accepted_audit_id == current_audit_id
assert run_authorization_arrived_after_current_audit_report
assert current_code_commit == audited_HEAD
assert actual_inputs_and_write_paths_match_approved_contract
```

## 运行与记录

- 执行前固定本轮 `run_id`，核对输入版本、代码提交、配置、依赖/环境、随机种子（适用时）、命令和输出位置。大文件可使用已有稳定版本号或强校验和；仅用文件名、修改时间或行数时须声明指纹较弱。
- 使用批准的入口执行。运行日志写 `scripts/logs/`；配置与指纹写 `scripts/config/`；正式表格和图件分别写 `results/data/`、`results/plot/`。PID、进度与恢复状态共用 `scripts/logs/runtime/`，不作为科研结果。
- 每次尝试记录开始/结束、退出码、失败与重试、实际资源和产物状态。只有获批准的运行参数范围内的环境、调度、缓存或可恢复故障可在 Runtime 内重试；不得在运行中静默改代码、换源数据或改统计口径。
- 逐项核对预期输出是否存在、是否完整以及适用的 schema、样本量、分母、缺失、数值边界和收敛/优化状态。检查结果是运行事实与异常线索，不代替独立审计。性能明显不满足获批规模时记录计时与资源证据，交后续分类；需要改代码则返回 Building。
- 为本次运行保存可追溯的清单：`run_id`、Building `audit_id`、Spec/Plan 指纹、代码提交、输入身份与指纹、配置指纹、完整命令、环境、输出路径和每项结果的大小/摘要或其他明确的身份依据。对清单的稳定序列化内容计算 SHA-256 作为 `run_hash`；说明采用的序列化和摘要方法，避免把路径或时间戳伪称为内容校验。不同运行或变更后的产物不得共用同一 `run_hash`。

## 阶段产物与停止

按 [Runtime Report 模板](../templates/runtime-report.md)在 `audits/runtime/report/` 下生成与 `run_hash` 对应的事实记录，例如 `audits/runtime/report/runtime_<run_hash前12位>.md`；多次运行保留各自的记录，不以新记录覆盖仍需追溯的旧运行。它是供后续独立审计的执行证据，不是 Runtime Audit；包含成功、失败或部分完成的事实、全部尝试和结果清单，不写“已通过 Runtime Audit”。一次性探查脚本、预览表和临时 JSON/CSV 用毕删除；被审计引用的异常证据先转入该记录或结果记录。`reports/` 仅在 Runtime Finish 生成面向结果验收的交付说明。

Runtime 完成后停止。成功且完整的运行交给后续独立 Runtime Audit；失败或部分完成的运行先记录事实并按原因返回 Runtime、Building 或 Proposal。不得在同一轮自行完成审计、修复、重跑及最终交付。
