# Runtime 阶段大纲

**职责：**在已接受的 Building Audit 与用户运行授权下，使用受审代码和合格源数据完成正式分析。

**关键边界：**运行前锁定 Spec、代码、数据和写入位置；每次尝试记录命令、配置、环境、日志、失败与产物，并以 `run_hash` 绑定最终清单。Runtime Report 只记录事实。可在已批准边界内处理运行条件问题；需要改代码回 Building，需要改科学方案回 Proposal。

**产物与停止：**正式结果、日志/配置、[Runtime Report](../templates/runtime-report.md)。成功运行后停止，转入独立 Runtime Audit；不能自行宣布结果已获接受。Agent 执行规则见 [Runtime 参考](../references/runtime-stage.md)。
