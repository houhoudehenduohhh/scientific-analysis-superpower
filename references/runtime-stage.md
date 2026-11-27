# Runtime：正式运行

本阶段只执行已批准的科研功能单元，形成事实性的 Runtime Report；不自行审计结果或宣布结果可交付。

## 入口门禁

在**每次正式运行前**核对并记录：

1. 当前 Proposal 的 Build Plan 及拟执行步骤引用的 Task MD 已获批准，源数据身份、资格与目标输出仍适用；
2. Building Audit 的结论为 `PASS`，或用户已明确接受 `PASS_WITH_NOTES` 的限制；`audit_user_decision=accepted`、`accepted_audit_id=audit_id`，且用户在看到这份报告后的后续消息明确授权运行；
3. 待运行的代码提交与该 Building Audit 审查的 `HEAD` 一致；受审代码、依赖或会改变计算语义的配置若已变更，先返回 Building；
4. 实际输入与 Build Plan 和 Task MD 的批准身份、版本和资格相符；写入目录、命令及预计资源在获批范围内。

任一条件缺失、矛盾或无法核实，停止并报告缺口。不得从“批准 Spec”“继续”或较早的运行许可推断当前版本已获放行。

正式入口前必须逐项作阻塞式判断，任何一项为假或未知都不能启动命令：

```text
assert spec_plan_and_referenced_tasks_approved_for_current_versions
assert current_spec_plan_and_task_identities_match_building_audit
assert building_audit_status in {PASS, user_accepted_PASS_WITH_NOTES}
assert audit_user_decision == accepted
assert accepted_audit_id == current_audit_id
assert run_authorization_arrived_after_current_audit_report
assert current_code_commit == audited_HEAD
assert actual_inputs_and_write_paths_match_approved_contract
assert requested_steps_within_current_user_authorization
assert prerequisite_milestones_accepted_and_inputs_match_their_audited_hashes
assert no_unreviewed_upstream_output_is_used
```

## 运行与记录

执行前按 [Runtime Harness 命令](sdd-harness.md#runtime-命令)核对当前可执行范围。正式步骤从 `runtime-run` 启动，协调者使用返回的尝试身份派发独立审查，通过 `runtime-review` 登记裁决，并用 `runtime-report` 生成已核对的节点事实汇总。

若派发 Runtime 执行子 Agent，在创建工具参数中显式传入 `model: gpt-6.2-sol` 和 `reasoning_effort: low`。

按批准的 Build Plan **Runtime 步骤图**执行，不把 Build Task 编号当作运行顺序。一个 Build Task 可对应发布、计算、回收等多个步骤；同一验收节点内，已满足前置条件且写入互不冲突的步骤可并行。只运行用户本次授权的节点和步骤；接受上游节点不自动扩大授权。每步完成后按 [自动步骤审查](../templates/runtime-task-reviewer-prompt.md)由未执行该步的 Reviewer 检查，审查通过才解锁其依赖步骤。

旧版已批准 Build Plan 若没有步骤图和验收节点，先在 Proposal 补齐并让用户批准受影响的计划；不得由 Agent 事后自定审计节点或把“运行至 Task N”直接解释成最终完成。

- 执行前固定本轮 `run_id`，核对输入版本、代码提交、配置、依赖/环境、随机种子（适用时）、命令和输出位置。大文件可使用已有稳定版本号或强校验和；仅用文件名、修改时间或行数时须声明指纹较弱。
- 使用批准的入口执行。运行日志、进程状态和恢复记录写 `scripts/logs/runtime/`，输入配置从 `scripts/config/` 或已批准路径读取。步骤产物先写 `.tmp/sdd/<plan-id>/runtime/<run_id>/attempts/<step_id>/rNN/`。同节点的下游步骤读取已通过步骤审查的暂存文件，跨节点步骤读取已接受节点的发布文件。
- 每次尝试记录开始/结束、退出码、失败与重试、实际资源和产物状态。只有获批准的运行参数范围内的环境、调度、缓存或可恢复故障可在 Runtime 内重试；不得在运行中静默改代码、换源数据或改统计口径。
- 逐项核对预期输出是否存在、是否完整以及适用的 schema、样本量、分母、缺失、数值边界和收敛/优化状态。检查结果是运行事实与异常线索，不代替独立审计。性能明显不满足获批规模时记录计时与资源证据，交后续分类；需要改代码则返回 Building。
- 为本次运行保存可追溯的清单：`run_id`、Building `audit_id`、Spec/Plan 指纹、按完整 ID 绑定的 Task MD 指纹、代码提交、输入身份与指纹、配置指纹、完整命令、环境、输出路径和每项结果的大小/摘要或其他明确的身份依据。对清单的稳定序列化内容计算 SHA-256 作为 `run_hash`；说明采用的序列化和摘要方法，避免把路径或时间戳伪称为内容校验。不同运行或变更后的产物不得共用同一 `run_hash`。

每步尝试记录 `step_id`、`attempt`、受审输入哈希、产物哈希与 `step_run_hash`；验收节点完成时，用固定排序的步骤哈希、上游已接受节点审计 ID、代码/Spec/Plan/Task MD/配置身份计算该节点的 `run_hash`。后续节点只引用已接受的上游身份，不改写旧节点的 `run_hash`。最终全链条审计绑定按依赖顺序排列的已接受节点审计 ID 与节点 `run_hash` 所形成的 `chain_hash`；计算方法和清单须可复核。

## 自动步骤审查与返工

- 每次运行尝试先写事实记录，再派独立步骤 Reviewer。Reviewer 对照该步所属 AC、上游身份、输出合同和实际证据给出通过／需修复／证据不足及返工判定卡；不能只凭退出码放行。
- 同一步最多五轮**修复后复审**，每轮保留原记录、修复、重跑和审查差异。只允许在已批准的环境、传输、缓存、可恢复状态或参数范围内自动重试；失败的步骤及其下游停止，互不依赖的分支可继续。未完成的节点不生成通过的节点审计。
- 路由须同时核对拟修改对象与实际改动：只改获准运行条件留在 Runtime；源码、依赖或计算语义改变返回 Building，补回归测试及任务复审，新提交重新经过 Building Audit 和用户门禁；源数据资格、目标量或科学算法改变返回 Proposal 并重批 Spec/Plan。根因不明先作限定诊断；五轮仍有实质问题或无法分类时停止受影响链并交用户裁决，不猜测路由。
- 依据批准的依赖图列出受影响输出及下游。新尝试只使被改动影响的审计与产物失效；未受影响的上游可在身份和接口复核后复用。不得把旧运行产物静默接到新代码、输入或配置。

需要回到 Building 时，通过 `runtime-return` 记录用户裁决。Harness 归档前一周期的步骤、审计和 Building 任务证据，并清空本轮修复计数及 Building 门禁。用现有获批规格重新注册任务，生成不同版本的证据与审计，经用户的新接受与运行授权后再执行。

当前批次节点均获接受且还有后续批次时，按 [建设批次交接](sdd-harness.md#建设批次) 保存原审计和已发布结果，再定稿下一批。最终全链条审计等完整计划的节点均获接受后进行。

需要回到 Proposal 时，先登记 `runtime-return` 以保存旧规格快照和两阶段证据，再修订规范路径下的 Build Plan 与 Task MD。用户批准修订版后，用 [Harness 的 `proposal-rebind`](sdd-harness.md#runtime-命令) 绑定新规格并开始新 Building 周期。新审计与运行授权绑定新的合同和 `run_id`。

## 阶段产物与停止

采用当前路径约定的 Build Plan，其运行工作区为 `.tmp/sdd/<plan-id>/runtime/<run_id>/`。Harness 根据 [Runtime Report 模板](../templates/runtime-report.md)在其中的 `reports/` 记录每次尝试和节点事实，`reviews/` 保存独立步骤审查及技术初审，`evidence/` 保存合同、授权、审计裁决和发布绑定，`attempts/` 保留每次尝试的文件。早期已绑定运行继续使用原路径。`audits/runtime/` 根目录存放正式 Runtime Audit Markdown。功能单元根目录的 `reports/` 在 Runtime Finish 保存面向读者的交付说明。

当前获准验收节点的步骤完成后停止并进入[节点 Runtime Audit](runtime-audit.md)；未完成时保留事实和返工记录，按上方自动循环或返回阶段处理。正式节点审计一经生成即停在用户门禁，不得自行批准后续节点。所有节点接受后再进行独立的全链条结果审计；未获接受前不得 Runtime Finish。

任务按完整 Task ID 和 AC 绑定运行证据。复用产物前核对身份、接口和资格，并沿批准依赖图重验受影响输出。
