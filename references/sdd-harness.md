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

状态转移失败时，协调者必须停在当前状态。`CHANGES_REQUIRED` 在第五轮前只能进入 `fix_round_pending`。没有修复报告、测试证据和 Re-review，不能进入 `task_complete`。Final Review 必须登记当前 HEAD 的整体审查证据。整体审查为 `CHANGES_REQUIRED` 时，正式 Building Audit 只能登记为 `CHANGES_REQUIRED` 或 `BLOCKED` 并提交用户裁决。Runtime 需要整体审查和正式 Building Audit 均通过。

任务状态转移还检查证据角色：Implementer 完成报告必须包含 `Status: DONE` 或 `DONE_WITH_CONCERNS`、提交信息和 TDD 证据；Task Review 和 Re-review 必须包含精确的 `Verdict: PASS` 或 `Verdict: CHANGES_REQUIRED`。已绑定的报告不可修改，修复轮次必须创建新的不可变 Fix Report 和 Re-review 报告。

在注册或派发每个任务前，协调者必须运行：

```text
python skills/subagent-driven-development/scripts/sdd-harness.py verify-build-plan <state.json> --artifact <build_plan.md>
python skills/subagent-driven-development/scripts/sdd-harness.py verify-task-spec <state.json> --artifact <Task-Spec.md> --build-plan <Build-Plan.md>
```

这两个命令校验模板结构。布局不合格时停止 Proposal 交接或任务派发，内容审查和用户批准仍按阶段规则处理。

## 功能单元 Git 初始化

Proposal 校验 `build_plan.md` 并呈现其中的 `功能单元 Git 根目录`。获批后，协调者在获批目录的 `.tmp/sdd/` 下保存批准记录，例如 `spec-approval-01.json`。记录包含 `build_plan_sha256`、`task_specs`（完整任务 ID 到 SHA-256 的映射）、`approved_at`（含时区）和 `user_message_ref`。

Building 默认在获批功能单元上运行以下命令，其中 `WORKTREE` 就是获批目录：

```text
python <Harness路径> init <WORKTREE>/.tmp/sdd/<计划名>/state.json --build-plan <PLAN> --evidence <批准记录.json>
```

若需要先创建隔离 worktree，先用 `prepare-git <PLAN> --evidence <批准记录.json>` 建立功能单元基线，再按 worktree 规则准备独立工作树。将 `init` 的状态路径指向该工作树下的 `.tmp/sdd/<计划名>/state.json`，并传入 `--worktree <WORKTREE>`。Build Plan、Task MD 和批准记录仍引用获批目录中的原文件。实现和测试需要的文件应先核对是否已包含在工作树基线中。每个计划使用一处状态目录。

旧计划若已有 Harness 状态，且计划的路径和指纹与状态记录一致，可沿用原工作区续跑。首次初始化使用包含功能单元 Git 根目录的获批计划。

## Runtime 命令

沿用同一 `state.json` 和 `sdd-harness.py`。命令表中的动作都使用 `python <Harness路径> <state.json> <命令>`。

新计划的合同、交接和运行回执保存在本次工作树的 `.tmp/sdd/<计划名>/runtime/<run_id>/evidence/`。Harness 写入的尝试与节点事实记录在同次运行的 `reports/`，独立步骤审查在 `reviews/`。旧运行按原绑定路径恢复。科学输入可使用方案已批准的外部路径，合同继续记录其身份和指纹。

新计划的运行输出先写入对应运行的 `attempts/`。节点获接受时，Harness 核验并发布到 `results/<data、plot 或 smoke_test>/<运行版本>/<逻辑路径>`，保留旧次结果。完成所有节点验收后另做最终全链条审计，单节点也使用同一流程。

| 命令 | 输入及职责 |
|---|---|
| `runtime-init --artifact <合同.json> --evidence <Building接受记录.json>` | 从当前 Building Audit Gate 绑定审计、已批准版本、步骤图和运行合同。 |
| `runtime-authorize --evidence <运行授权.json>` | 记录用户在审计后明确授权的步骤。这条记录与审计接受分别绑定。 |
| `runtime-status` | 查询当前节点、步骤和已有证据。 |
| `runtime-run <step_id> --actor <执行者> [--evidence <重试记录.json>]` | 核对授权和依赖后运行指定步骤，记录本次尝试。 |
| `runtime-interrupt <step_id> --evidence <中断确认.json>` | 确认旧尝试的进程已停止后记录失败，交独立步骤审查。 |
| `runtime-review <step_id> --evidence <步骤审查.json>` | 绑定对本次尝试的独立审查和逐 AC 裁决。 |
| `runtime-report <node_id>` | 生成并绑定当前节点的事实汇总，供独立审查使用。 |
| `runtime-scope <node_id或final_chain>` | 生成当前审查范围的证据索引与哈希。 |
| `runtime-audit-repair <node_id或final_chain> --evidence <初审返工.json>` | 正式审计登记前，按同一范围内的独立初审证据集中修复一次，重审受影响的步骤和节点。 |
| `runtime-audit <node_id或final_chain> --evidence <审计登记.json>` | 绑定正式审计报告并停在用户门禁。 |
| `runtime-accept <node_id或final_chain> --evidence <用户接受.json>` | 登记用户对所呈现版本的明确接受。 |
| `runtime-return <step_id、node_id或final_chain> --evidence <返工裁决.json>` | 绑定当前步骤或正式审计的裁决，按受影响范围返工或交回上游。 |
| `proposal-rebind --build-plan <修订的build_plan.md> --evidence <新Spec批准.json>` | 仅在 Runtime 返回 Proposal 后登记用户新批准的计划和任务指纹，开始新 Building 周期。 |
| `runtime-finish --artifact <交付说明.md>` | 核对最终审计接受和证据身份，登记交付说明。 |

协调者负责从对话取得真实的用户裁决、派发独立 Agent 并记录身份。Harness 校验提交给它的版本、范围、字段和证据，聊天用户与子 Agent 身份由调用方提供。

合同记录 `run_id`、`code_root`、`code_commit`、`build_plan_sha256`、`task_specs`、`inputs`、`nodes` 和 `steps`。节点与步骤的 `needs` 从获批计划转录，步骤还绑定 `node`、`task_id`、`acs`、输入和输出、配置、命令参数数组以及 `resources.timeout_seconds`。当前 CLI 串行执行步骤，同节点内仍按依赖关系选择下一步。

步骤使用获批的可执行文件绝对路径和 `executable_sha256`。配置可为空，提供时将路径和 SHA-256 写入 `config`。命令参数用独立的 `{input:输入ID}`、`{output:逻辑路径}`、`{output-dir:results/data}`、`{upstream:步骤ID:逻辑路径}` 等参数引用受绑定文件。需要调用外部或未跟踪的脚本时，显式列入 `code_inputs` 并绑定内容。运行所需的环境变量从 `environment` 声明。为保持代码来源一致，运行工作树中的未跟踪代码文件也须纳入绑定或移出运行工作树。

步骤环境由合同变量和 Harness 提供的固定平台变量组成。合同键名不区分大小写地禁止以下前缀：`PYTHON`、`LD_`、`DYLD_`、`R_`、`NODE_`、`PERL`、`RUBY`、`LUA_`、`DOTNET_`、`COMPLUS_`。禁止的完整键名为 `CLASSPATH`、`JAVA_HOME`、`JAVA_TOOL_OPTIONS`、`_JAVA_OPTIONS`、`JDK_JAVA_OPTIONS`、`BASH_ENV`、`ENV`、`ZDOTDIR`、`PSMODULEPATH`、`PATHEXT`、`SYSTEMROOT`、`WINDIR`。`PATH` 使用平台分隔符列出所需的绝对目录。每个目录至少包含一个通过 `code_inputs` 绑定 SHA-256 的可执行文件。声明的二进制必须是该 `PATH` 中首个同名可执行文件，Harness 在运行前重查其身份。审计应核对受审源码调用的所有子命令和相关运行库。Harness 信任受审程序，无法枚举它动态加载的所有依赖。

Building 交接记录将 `audit_id`、`report_sha256`、`assessment`、代码与规格指纹、`contract_sha256`、`spec_approval_ref`、`report_presented_at`、`accepted_at`、`acceptance_ref` 和已接受限制关联起来。单独登记运行授权的 `audit_id`、`contract_sha256`、`authorized_at`、`user_message_ref`、`steps`。用户在看过 Building Audit 之后，可在一条消息中分别表达接受和运行授权。

步骤审查 JSON 使用 `step_run_hash`、`reviewer`、`verdict`、逐 AC 的 `acs`、`route`、`report`。正式审计登记使用 `scope_hash`、`auditor`、`assessment`、`report`、`limitations`、`route`；用户接受使用 `audit_id`、`scope_hash`、`accepted_at`、`user_message_ref`、`accepted_limitations`。成功裁决的 `route` 为 `null`。接受记录独立保留，登记后的审计 Markdown 保持原样。

正式审计等待裁决期间可以只读查询状态和审查范围。唯一能推进状态的命令是针对当前审计且身份匹配的 `runtime-accept` 或 `runtime-return`。另一独立节点即使已就绪也须等当前裁决。

Runtime 内返工记录绑定本次 `step_run_hash` 或审计 `scope_hash` 并写明原因和拟修复对象。正式报告后的返工裁决同时包含 `decided_at`、`user_message_ref` 和适用的 `audit_id`。需要重跑节点或全链条时，列出返工 `steps` 及受影响运行条件 `changes`。

上下游产物同时受损时，用最早受影响且已有正式审计的节点作为本次 `runtime-return` 的范围。在同一份 `artifact_loss` 清单中列明该范围及其受影响下游的已审损失，`steps` 列出这些产物的生产步骤。Harness 在归档前核对受影响范围和未变更证据。下游步骤仍须等上游新审计获接受，下游重跑须重新授权。

返回 Building 或 Proposal 后，`state.json` 的 `building_history` 和 `runtime_history` 保留旧周期证据，新周期重新注册任务、累积任务修复轮次并生成 Building Audit。为新周期的账本、报告、合同、裁决、运行授权使用新路径，并采用新的 `audit_id` 和 `run_id`。返回 Building 时沿用现有已批准规格，以新提交经过 Building Audit 并登记用户新的接受与运行授权。

返回 Proposal 时，Harness 先将已批准的 Build Plan 和 Task MD 快照写入 `<state.json 所在目录>/history/<旧 run_id>/`。此后可在规范路径修订文档，使用 `status` 查看归档。用户批准修订版后，将文档的 `decision` 和 `approval_status` 更新为 `approved`，计算最终 SHA-256。`proposal-rebind` 接收 `build_plan_sha256`、`task_specs`（完整任务 ID 到 SHA-256 的映射）、`approved_at`（含时区的时间）和 `user_message_ref`（返工裁决之后的新批准消息）。重绑定后逐个注册这些 Task MD 并走完整 Building 流程。新的 `runtime-init` 接受记录用 `spec_approval_ref` 引用本次批准消息，另行登记运行授权。

已开始但没有结束记录的尝试须先核对进程。确认已停后，用 `run_id`、`step_id`、`attempt`、`started_at`、`confirmed_not_running: true`、`operator`、`reason` 和 `observed_at` 登记中断。该尝试仍须经过独立步骤审查才可重试。
