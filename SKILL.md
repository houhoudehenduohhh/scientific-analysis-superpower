---
name: scientific-analysis-superpower
description: Route one scientific-analysis functional unit through Proposal, Building, independent audits, Runtime, and result delivery with explicit user approval gates.
---

# Scientific Analysis 总调度器

本文件只判定当前状态、调用下一个模块并守住门禁。阶段方法由链接的 Skill、`references/` 和 `templates/` 定义。`docs/` 只供人工审阅，不是执行依据。

## 每次启动先定位状态

1. 确定本次**一个最小功能单元**及用户当前目标。若路径未确定且无法从上下文得出，只询问必要的路径或范围。
2. 按用户目标和现有绑定定位本次 Proposal。前轮完成后开展独立补充研究时，走新一轮 Proposal。恢复或返工时，沿用所选计划绑定的工作区。若有多轮且无法判断要继续哪一轮，只确认轮次。读取该轮 Build Plan、拟执行 Task MD 的批准身份及 Runtime 步骤／验收节点图；Git 代码提交和 SDD 账本；最新 Building Audit 的版本与用户裁决；当前授权范围、各节点的运行记录、`run_hash`、审计版本与用户裁决；最终 `chain_hash` 和全链条审计状态。只读取判断当前阶段所需的文件，不把历史报告的批准沿用到新版本。
3. 先检查最早未通过的门禁，再按下表选择**唯一当前阶段**。若记录冲突或缺失，停在该门禁补证据；用户说“继续”“运行”，或在一条消息里同时要求计划和执行，都不能代替门禁批准。
4. 完成当前阶段后，报告本阶段产物、版本、门禁状态和**建议下一步调用的模块**。到达用户门禁时必须停止，不能在同一轮自行批准并越级。

Building 只能通过 SDD 入口完成。任何代码改动、编译检查或单次测试都不能单独标记为“Building 完成”。在路由到 Building Audit 前，必须存在当前计划的 SDD 账本、每个已执行任务的完整 ID、Task brief 快照、实现报告、提交范围、Task Review/Re-review 结论和整体 Review 证据。缺任一项就停留在 Building，继续调用 SDD。

进入 Building 后，按[前置与工作区规则](references/build-stage.md#前置与工作区)在获批功能单元内建立或复用独立 Git，记录基线和 SDD 工作区。Building 完成后按 [Build 门禁检查](references/build-gates.md)登记审计证据。

SDD 状态由 [Harness](references/sdd-harness.md) 管理。协调者必须在每个任务和每轮修复前后使用 `sdd-harness.py` 检查合法状态转移。提示词不能单独改变阶段状态。

到达 Runtime 交接后，按[运行规则](references/runtime-stage.md)调用同一个 Harness 的 Runtime 命令，从已接受的 Building Audit 和单独的运行授权开始；节点审计、最终审计和交付也由该入口推进。

状态必须显式记录。实现 Agent 中断、失败或返回非 DONE 时为 `building_incomplete`，禁止 Reviewer 完成判断、Final Review、Building Audit 和 Runtime。Task Reviewer 缺失时任务不能完成，Final Review 缺失时不能生成正式 Building Audit。最终回复必须列出当前状态、账本、任务 ID、提交范围、Task Review、Final Review 和 Building Audit 证据状态。

Task Review 返回 `CHANGES_REQUIRED` 或存在 Critical/Important finding 时，状态必须变为 `fix_round_pending`。此状态只能执行“派发修复 Agent → 写修复报告和测试证据 → 生成修复差异 → Re-review → 记录 ADDRESSED/NOT_ADDRESSED”。在五轮上限前，禁止结束回复、推进下一个任务、进入 Final Review、生成 Building Audit 或进入 Runtime。修复循环必须通过 `scripts/check-fix-loop`，否则保持在当前 Task。

## 阶段路由

| 当前证据 | 当前阶段 → 调用模块 | 本阶段产物与停止点 |
|---|---|---|
| 首次规划、规格缺失、补充分析或需实质修订科学方案/数据资格 | **Proposal** → [阶段规则](references/proposal-stage.md)；使用 [Build Plan](templates/build-plan.md) 和 [Task Spec](templates/task-spec.md) 模板，并通过 Harness 格式校验 | 本轮 `specs/proposal-<序号>-<主题>/` 内的 Build Plan 和 Task MD；**停在 Spec Gate**，等用户批准当前 Build Plan 和 Task MD。 |
| 当前规格已产出，但本轮版本尚无用户批准 | **Spec Gate 等待** → 只呈现本轮规格、未决事项与所需裁决；若用户提出修改则返回 Proposal | 不重新生成或执行 Build；建议用户审阅、批准或提出修订。 |
| 当前总览与拟执行任务已获批准；计划任务未完成，或审计要求修改代码 | **Building** → [科研边界](references/build-stage.md) → [subagent-driven-development](skills/subagent-driven-development/SKILL.md)；其中按任务调用 TDD、实现 Agent、独立 Task Reviewer 与修复复审 | 代码、测试、提交及任务审查证据。SDD 任务全完后按其流程衔接整体 Review；遇方案/计划实质变更或五轮后仍有实质缺陷则停下交用户裁决。 |
| 任务均完成，但当前提交尚无 Building Audit；或代码修复后旧报告已失效 | **Building Audit** → [SDD 最终 Review](skills/subagent-driven-development/references/final-review.md) → [Building Auditor Prompt](templates/building-auditor-prompt.md)；使用 [Building Audit 模板](templates/building-audit-report.md) | 先完成整体审查及最多一次实现缺陷修复与复审。计划正式运行时，按拟运行环境核实并审查 Runtime 合同，再将正式报告与合同登记到同一门禁；**停在 Building Audit Gate**，等用户审阅、接受并在看到报告后授权运行。已完成的任务不重新派发。 |
| 当前 Building Audit 已生成，但用户尚未接受或尚未在看过报告后授权运行 | **Building Audit Gate 等待** → 呈现问题、限制与 `audit_id`；按用户裁决返回 Proposal/Building 或进入 Runtime | 不修复后自行放行，不重用其他版本的审计。 |
| Building Audit 已接受，且本次节点／步骤已获授权；该节点步骤尚未全通过 | **Runtime 步骤循环** → [运行规则](references/runtime-stage.md)、[事实记录](templates/runtime-report.md) 与 [自动步骤审查](templates/runtime-task-reviewer-prompt.md) | 按批准的无环步骤图执行、独立审查及最多五轮运行条件修复；未通过的步骤不解锁下游。需改代码或科学方案时分别返回 Building／Proposal。 |
| 当前节点步骤均通过，尚无该节点正式审计 | **节点 Runtime Audit** → [审查规则](references/runtime-audit.md)、[独立 Reviewer](templates/runtime-auditor-prompt.md) 与 [报告模板](templates/runtime-audit-report.md) | 整体初审、最多一次允许范围内集中修复及复审后形成绑定节点 `run_hash` 的正式报告；**停在节点用户门禁**。 |
| 当前节点正式审计已生成，用户尚未接受当前节点报告 | **节点门禁等待** → 呈现节点完成与未验证范围，按用户裁决路由 | 不自动推进依赖节点，不扩大原运行授权。 |
| 前置节点已接受，但下一节点未在用户授权范围内 | **运行授权等待** → 呈现已接受节点、下一节点及所需运行范围 | 不启动新节点；接受旧审计不能替代新的运行授权。 |
| 当前建设批次的节点均获接受，计划还有后续批次 | **下一建设批次** → [批次交接](references/sdd-harness.md#建设批次) | 保存本批已验收证据，进入下一批 Proposal 和 Spec Gate。 |
| 全部节点审计均获接受、计划目标完成，尚无有效全链条审计 | **最终 Runtime Audit** → [审查规则](references/runtime-audit.md)、[独立 Reviewer](templates/runtime-auditor-prompt.md) 与 [报告模板](templates/runtime-audit-report.md) | 核对已接受节点哈希链、跨节点接口和最终科学结果，形成绑定 `chain_hash` 的独立正式报告；**停在最终用户门禁**。 |
| 最终全链条审计已生成但用户尚未接受当前最终报告 | **最终门禁等待** → 呈现结论、限制与返回建议 | 不交付，也不沿用旧版本的接受。 |
| 最终全链条审计已获接受，结果仍对应被审 `chain_hash` | **Runtime Finish** → [交付规则](references/runtime-finish.md) 与 [交付模板](templates/runtime-finish-report.md) | 只整理已审结果、复现信息与解释限制；交付后完成本轮 Proposal。 |

SDD 在当前建设范围内的任务全部完成后执行整体 Review。初审及最多一次自动修复、复审属于 Building Audit 形成前的内部证据，不设正式 `audit_id`；只有含任务验收索引的最终报告写入获批功能单元根目录的 `audits/building/` 后才触发用户门禁，**必须停在该报告，不能顺延 Runtime**。已有正式报告且用户裁决仍为 `pending` 时，不得借用自动修复规则继续返工。会话中断时依据 SDD 账本恢复未完成的审查，不重做已完成任务。

## 用户门禁

- **Spec Gate：**批准当前 Build Plan 和拟执行的 Task MD 版本；没有批准，不进入 Building。
- **Building Audit Gate：**当前报告为 `PASS` 或用户明确接受限制的 `PASS_WITH_NOTES`；`audit_user_decision=accepted`、`accepted_audit_id=audit_id`，且用户在看到报告后的后续消息明确授权运行。代码提交、Spec、Plan 或受审 Task MD 变化时重审；受影响的旧授权失效。
- **Runtime 节点门禁：**每个 Build Plan 验收节点的正式报告为 `PASS` 或用户明确接受限制的 `PASS_WITH_NOTES`；用户接受当前节点审计报告后才解锁获授权的依赖节点。Harness 用审计编号和节点指纹绑定该裁决。自动步骤审查无需逐项人工批准。
- **最终 Runtime Audit Gate：**全部节点获接受后另审全链条；当前报告为 `PASS` 或用户明确接受限制的 `PASS_WITH_NOTES`，用户接受当前最终审计报告后才可 Runtime Finish。Harness 用审计编号和全链条指纹绑定该裁决。新运行或受影响结果变更时重审。

## 返工路由与总规则

科学问题、源数据资格、概念算法或关键假设改变 → Proposal；代码偏离批准方案或需要工程改动 → Building，随后重新 Building Audit；运行环境、获准配置、缓存或可恢复失败且代码与方案仍适用 → Runtime。结果“不理想”先由 Runtime Audit 分类，不直接据此修改 Build Plan 或代码。Runtime Report 只是事实记录，不等于 Runtime Audit。

只围绕一个功能单元工作。正式文档默认中文；`specs/`、`reports/`、`audits/` 只存 Markdown。一次性探查文件用毕删除；SDD 临时工作区留存供 Agent 复查与恢复。`scripts/profile_data.py` 是可选的只读数据概况工具，不能代替源数据资格和科学判断。每次回复说明**当前阶段、所用依据、产物、门禁状态、下一步模块**，不把测试通过或进程退出码当作科学结果可信的证明。
