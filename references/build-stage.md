# Building 阶段：科研边界

本文件只说明原版 [subagent-driven-development](../skills/subagent-driven-development/SKILL.md) 在科研功能单元中的适用边界；任务派发、提示词、取证命令、返工及恢复仍由该 Skill 定义。

## 前置与工作区

- 当前 `build_plan.md` 与本轮 Task MD 已获用户明确批准，源数据身份及资格已确定。方案或数据口径发生实质变化时返回 Proposal；Build Plan 的实质变更先交用户确认。
- 从 Build Plan「目标与边界」读取获批的 `功能单元 Git 根目录`。Building 在该目录复用或建立独立仓库。上层仓库已跟踪该单元时，列出冲突并交用户处理；上层的 Git 历史和索引由用户管理，Agent 不得自行移动或备份上层 .git 来绕过冲突。
- 默认在获批功能单元根目录执行。已有 Harness 状态时续用已绑定工作树。同一计划的各节点、实现、审计和返工共用该工作树。确需新建隔离 worktree 时，先由用户明确批准完整路径，再按 Harness 规则登记。
- 使用 [Harness 的 Git 初始化命令](sdd-harness.md#功能单元-git-初始化)登记获批计划。新仓库建立空基线，需进入版本控制的文件按任务范围明确暂存。
- 在已确定的最小功能单元内核对 `specs/`、`scripts/`、`results/`、`reports/`、`audits/` 的职责边界；按已批准计划建立本阶段实际需要的 `scripts/build/`、`scripts/config/`、`scripts/pytest/`、`scripts/smoke_test/`、`scripts/logs/`、`results/smoke_test/`、`audits/building/`。`reports/` 与 `audits/` 只放 Markdown 正式文档，不为追求目录齐全创建空占位文件。
- 在有首个提交的 Git 工作树中执行。每个任务开始前记录 `BASE`，实现和修复各自提交，再以对应 `BASE..HEAD` 生成审查差异。派审前检查未提交改动，避免遗漏待审代码。提交只固定待审版本，不代表任务通过。
- `review-package` 要求工作树干净。冒烟产物应按项目约定明确纳入版本控制或排除在 Git 状态之外；报告仍记录输入、命令、产物路径与必要指纹，不能仅为通过干净检查而丢弃审计证据。
- 实现和审查使用获批准计划的单任务 brief、报告和差异；Task Reviewer 只获取该任务适用的输入、输出和验收条件。完整 Build Plan 与跨任务数据流留给最终 Reviewer。
- SDD 进度账本、brief、任务报告和审查包放在当前功能单元的临时工作区。未完成的返工保留以便恢复。保留临时工作区供 Agent 复查与恢复，人工验收使用正式报告。
- 整体复审后，Building Auditor 在正式报告第 6 节集中登记每项任务的目的、各 AC 成功条件、当前判定、已验证行为和未验证范围，并摘要记录影响 AC 的返工。技术任务报告和独立审查记录留在 SDD 临时工作区。
- 将新增主入口和实现模块写入 `scripts/build/`。Building gate 核对从受审基线到 HEAD 的 Git 树变化和拟新增路径。复用 scripts/build/ 之外的既有入口时，Git 内容与文件模式必须保持一致。功能单元冒烟结果使用 `results/smoke_test/`，必要时在本次结果目录附 `smoke-report.md`。运行日志使用 `scripts/logs/`。

## 测试与运行边界

- 按 SDD Implementer Prompt 中的 TDD 契约完成适用的行为测试。代码或行为变更必须记录 RED、GREEN 和必要的 REFACTOR 证据；配置、文档和生成文件可记录例外。期望值应来自独立依据；需要时使用手算夹具、性质测试、合成输入或获准的小规模真实样本。
- pytest 临时夹具用 pytest 自管目录。需要自定 `--basetemp` 时，放在当前计划 SDD 工作区下的独立测试目录。任务内执行定向测试，交付前执行适用的全套测试。完成本次获批建设范围的所有任务后执行适用的语法、导入、静态检查和最小入口冒烟测试，并记录命令、输出、输入身份和对应提交。
- Building 不对预定正式源数据运行主生产分析，也不产出正式科研结果。测试通过不等于科学结果可信。

## 返工与门禁

- 每个任务由独立 Reviewer 对契约符合性和代码质量作双重结论，Agent 在已批准计划内自动完成任务级修复及局部复审，不设置逐任务人工门禁。每任务最多五轮；仍有实质缺陷时暂停依赖任务，带完整证据交用户决定。非阻断问题如实列入最终报告，由用户决定是否接受。
- 本次建设范围的全部任务结束后，按 [最终 Review 规则](../skills/subagent-driven-development/references/final-review.md)由一名独立 Reviewer 审查当前建设范围的整段代码变更；可修复的实现缺陷最多集中修复一次并局部复审。初审与复审先存 SDD 临时工作区；循环结束后才在获批功能单元根目录的 `audits/building/` 直接形成一份 [正式 Building Audit 报告](../templates/building-audit-report.md)，关联当前 Spec、Plan、代码提交、任务审查和验证证据。正式报告生成即停止，用户接受前不得进入 Runtime。
