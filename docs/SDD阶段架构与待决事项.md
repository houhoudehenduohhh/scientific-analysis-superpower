# SDD 阶段架构与待决事项（讨论稿）

> **待检查状态栏** · 以下事项需在首次实际使用中核实；“待实测”表示已有执行规则，尚未完成实战 check。
>
> | 检查项 | 状态 | 待确认内容 |
> |---|---|---|
> | Task Review 是否需要人工介入 | ☑ 已确定 | 每任务由独立 Reviewer 审查，Agent 在已批准计划内自动修复和复审；每任务最多五轮，仍有实质缺陷则交用户裁决。 |
> | Building 与 Runtime 的承接 | ☐ 待实测 | 已写入 Runtime、Runtime Audit 和 Runtime Finish 规则；需用实际运行检验性能问题、代码返工及重审路线。 |
> | SDD 临时文件的裁决 | ☐ 未完成 | 确定任务报告、Review、diff 与账本的保留期限和删除条件。 |

![mermaid-diagram](E:\10Project\scientific-analysis-superpower\docs\mermaid-diagram.png)

图中的 `task-N-*`、差异包和进度账本属于每份 Build Plan 的临时 SDD 工作区；

正式报告属于功能单元的 `audits/building/`。

箭头表示调用顺序与返工路线，不表示审计意见会自动获得用户批准。`verification-before-completion` 也适用于每个任务声称完成之前，图中只在最终出口画出一次。

**文件调用索引：**入口与阶段边界为根目录 `SKILL.md`、`references/build-stage.md`；

工作树和临时区由 `skills/using-git-worktrees/SKILL.md`、`skills/subagent-driven-development/scripts/{sdd-repo,sdd-workspace}` 处理。

SDD 的调度主文件是 `skills/subagent-driven-development/SKILL.md`；其 `references/{preflight,resuming,batching,handling-reports,cannot-verify,fix-loop,final-review}.md` 在图示对应分支调用。

每任务由同目录 `scripts/{task-brief,review-package}`、`implementer-prompt.md`、`task-reviewer-prompt.md`、`re-review-prompt.md` 执行提取、实现、审查与复审。测试方法见 `skills/test-driven-development/{SKILL.md,writing-good-tests.md}`。

整体审查使用 `skills/requesting-code-review/{SKILL.md,code-reviewer.md}` 和 `templates/building-audit-report.md`；

任务反馈核实、根因调查与完成前取证分别使用 `skills/receiving-code-review/SKILL.md`、`skills/systematic-debugging/SKILL.md`、`skills/verification-before-completion/SKILL.md`。`systematic-debugging` 目录中的 `root-cause-tracing.md`、`defense-in-depth.md`、`condition-based-waiting.md` 及其示例、`find-polluter.sh` 仅在对应故障调查时按需调用。

## 1. 前置契约与工作区

Proposal 先产出并获得用户批准的 Reader Spec 与 Build Plan。Reader Spec 规定科学问题、源数据资格、概念算法及结论边界；Build Plan 规定实现任务、接口、验证和 Review Focus。Building 只能在该批准版本内执行。`SKILL.md` 路由至 `references/build-stage.md`，随后用 `using-git-worktrees/SKILL.md` 建立或核对隔离工作树。`scripts/sdd-repo` 确认仓库，`scripts/sdd-workspace` 为该计划建立 `.tmp/sdd/<计划名>/`；`progress.md` 记录任务、提交、发现和裁决，`plan-path` 防止串用其他计划的账本。

任务切分由获批准的 Build Plan 决定。Building 的 `preflight.md` 检查任务依赖和接口冲突，`batching.md` 只处理同型小任务的执行组合，不重新决定科学或工程计划；`resuming.md` 用账本与 Git 提交恢复中断进度。实质性的 Spec 或 Plan 改动交用户重新确认。

## 2. 单任务 Build 与 TDD

`scripts/task-brief` 从 Build Plan 原文提取 `task-N-brief.md`。实现 Agent 只获得该任务 brief、必要接口、适用的 Reader Spec 约束与 `implementer-prompt.md`；不把全部项目文件灌入单任务上下文。实现时按 `test-driven-development/SKILL.md` 和 `writing-good-tests.md` 先写能证明目标行为的失败测试，再写最小实现、重构和自查。测试预期必须有独立依据；pytest、语法或导入检查以及小规模真实样本冒烟测试各回答不同问题，不能相互替代。实现 Agent 将完整执行记录写入 `task-N-report.md`，提交 Git；`handling-reports.md` 处理其疑问、顾虑或阻塞。

`scripts/review-package` 用任务开始前记录的 `BASE` 和当前 `HEAD` 生成完整差异包，不能用 `HEAD~1` 代替多提交任务的起点。Git 提交仅固定待审版本，不宣告任务通过。

## 3. 任务级审查与返工

独立 Task Reviewer 使用 `task-reviewer-prompt.md`，读取该任务 brief、实现报告、完整 diff 和约束，分别给出**任务契约符合性**与**代码质量**结论；完整报告保存为临时 `task-N-review.md`。`cannot-verify.md` 处理仅凭 diff 无法证明的要求。Review 意见应先核实：证据成立则修复，依据不足则补查，不成立则记录反证。`receiving-code-review/SKILL.md` 可以辅助核实。现已根据首次实际 Building 确定：任务级 Review 由 Agent 在已批准计划内自行核实、修复与复审；每任务最多五轮，实质问题仍未解决时停下交用户裁决。

有实质缺陷时，`fix-loop.md` 将原发现交回实现者；每轮修复提交后，`re-review-prompt.md` 只核对原发现与本轮修复差异，留下 `task-N-re-review.md` 和账本记录。最多五轮；前三轮优先原实现者，后两轮换新实现者并升级能力。五轮后仍有影响后续可信度的缺陷，暂停依赖任务并交用户裁决；非阻断问题可以带证据进入最终报告，由用户决定是否接受。任务级审查不代替整个分支的最终审查。

## 4. 整体 Building Audit 与人工裁决

全部任务完成后，`final-review.md` 调用 `requesting-code-review/SKILL.md` 的 `code-reviewer.md`，由**一名独立 Reviewer** 对完整分支及批准的 Reader Spec、Build Plan、源数据身份、任务审查和验证记录作追溯审查。整体初审及至多一轮集中修复、局部复审先保存在 SDD 临时工作区，不作为正式 Building Audit。循环结束后按 `templates/building-audit-report.md` 写入 `audits/building/` 唯一正式报告，绑定 Spec/Plan 哈希、待审提交、差异范围和 `audit_id`，然后停在用户裁决门禁。用户接受当前代码版本及必要的非阻断限制后，才可能进入 Runtime。

正式模板的 `Issues` 保留 Reviewer 的原始发现，`Human Disposition` 记录用户与 Agent 讨论后的逐条决定、证据、验收标准及影响的 Spec/Plan 条目。返工和复审按 `audit_id + finding_id + 新提交` 追溯。人可以接受、调整或不采纳建议，但不能把未裁决意见悄悄写成已批准修复。正式 Audit Gate 的裁决权在用户；任务级 Review 按已确定的 Agent 自动闭环规则执行。

### 模板来源与可迁移部分

| 当前模板 | 来源判断 | Superpowers 可作为改造底稿的文件 |
|---|---|---|
| `templates/reader-spec.md` | 本地科研模板，不是原版 Superpowers 模板 | `skills/brainstorming/SKILL.md` 的设计写作流程；原版没有对应的科研 Reader Spec 栏目表。 |
| `templates/build-plan.md` | 本地科研模板，不是原版 Superpowers 模板 | `skills/writing-plans/SKILL.md` 的计划头、任务示例、文件规划、测试和验收步骤。 |
| `templates/building-audit-report.md` | 以 Superpowers Reviewer 输出格式为骨架的本地化正式模板；科研栏目仍为本项目增补 | `skills/requesting-code-review/code-reviewer.md` 的 Strengths、Issues（Critical/Important/Minor）、Recommendations、Assessment 输出格式；`subagent-driven-development` 的任务 Review 与局部 Re-review 提示词。 |

原版 Superpowers 的最终 Reviewer 返回代码审查结论，然后进入分支收尾；它没有绑定源数据、Reader Spec、Build Plan、代码指纹和用户 Runtime 门禁的正式科研 Audit report。现已采用[按原版栏目顺序排版的正式模板](../templates/building-audit-report.md)，保留科学追溯、逐条人工修复裁决和版本门禁；[先前本地模板](building-audit-report-legacy.md)移入 `docs/` 留作对照。

## 5. 后发现问题时如何走第二轮

| 发现时点与问题性质 | 路线 |
|---|---|
| 当前 Task 的审查中发现实现错误 | 在同一任务返工循环补失败测试（适用时）、修复提交、局部复审；不必新建整份 Building Audit。 |
| 任务已完成或 Building Audit 已形成，发现实现错误 | 在正式报告补充发现与人工修复方向；创建返工任务，提交修复并审查受影响差异。代码 `HEAD` 改变后，旧 Building Audit 不再能授权新版本；重新进行相应整体审查并形成指向新版本的裁决。 |
| 科学目标、算法、源数据资格或关键假设有误 | 返回 Proposal，修订 Reader Spec 和必要的 Build Plan，重新取得批准，再实施与审查。 |
| 后续 Runtime 暴露输入、配置或运行产物问题 | 先确定根因及影响范围，再按 Runtime / Runtime Audit 的返工规则处理；若根因在设计或代码，分别返回 Proposal 或 Building。 |

回归测试用于固定**可以明确指定预期的错误行为**。不能为迎合 Reviewer 的猜测凭空编造测试预期。冒烟测试验证脚本在小规模真实输入上的连接与执行；正式生产运行仍须经过 Building Audit 门禁。

### Building 与 Runtime 的承接（规则已接入，待实测）

**Building 的 smoke test 发现的问题仍属于 Building。**例如真实小样本跑不通、输出口径错误、内存溢出，或速度明显无法支撑预定规模，都应在 Building 修复、补适当测试或性能基准，并复审受影响提交。不能因为是在“运行脚本”时发现，就推迟到正式 Runtime。若速度仅有可选优化空间而仍满足已批准的运行预算，可以记录为非阻断限制供用户决定。

**Runtime 才暴露的问题需要分类返回。**数据版本或输入资格不符、科学口径需变更时回 Proposal；算法转代码、调度、资源或恢复机制有缺陷时回 Building，修复提交须重新通过 Building Audit；只是运行参数、环境或可恢复的执行故障时，在不改变已审代码与科学契约的前提下可留在 Runtime 处理并重新记录运行证据。正式运行结果的异常或不理想先记 Runtime Report 的事实、输入/代码指纹和影响，再由 Runtime Audit 判断是否修订 Spec、代码或运行配置。Runtime Report 不是审计裁决。上述路径已写入本项目的 Runtime 阶段规则，仍待真实功能单元验证。

本地 Superpowers 的 SDD 到“任务 Review → 整体代码 Review → 分支收尾”为止；`verification-before-completion` 要求以实际测试证据支持完成声明，`finishing-a-development-branch` 在合并或 PR 前验证测试。检索其 skills 后，未见针对科研正式数据运行、结果审计或结果返工的独立 Runtime skill。本项目现已增加输入锁定、预检、运行指纹、运行报告、异常分流和 Runtime Audit 门禁。性能阈值由具体功能单元的已批准 Build Plan 给出；缺失时不能事后凭结果任意设定。

## 6. 临时文件清单与清理待决

当前 `sdd-workspace` 在功能单元内使用 `.tmp/sdd/<计划名>/`；计划不在该工作树时退到仓库 `.tmp/sdd/`。下表区分当前机制会生成的材料和运行时**可能**生成的材料，便于逐项决定保留期限。

| 文件或目录 | 产生环节与用途 | 原版 Superpowers 的处理 | 本地建议／待决 |
|---|---|---|---|
| `.tmp/sdd/.gitignore`、`<计划名>/plan-path` | 隔离临时工作区、绑定计划身份 | 对应工作区在仓库 `.superpowers/sdd/<计划名>/`，用 `.gitignore` 隔离并以 `plan-path` 绑定计划；最终审查干净且修复已合并后删除该计划工作区。 | 本地改为 `.tmp/sdd/`；何时删除待定。 |
| `progress.md` | 任务状态、提交、裁决、返工恢复账本 | 先把所有 `Ruling:` 逐条复制到最终给用户的消息，再删除计划工作区；Git 历史保留提交。 | 正式报告要接收必要追溯；原件是否保留待定。 |
| `task-N-brief.md` | Build Plan 单任务原文的派发快照 | 随计划工作区删除；计划正文仍在。 | 是否在审计接受后删除待定。 |
| `task-N-report.md`、修复追加记录 | 实现者的测试命令、输出、提交和顾虑 | 随计划工作区删除；提交与测试代码留在 Git。 | 重要证据应进入正式报告；原件是否留存待定。 |
| `review-BASE..HEAD.diff`、修复差异包 | Reviewer 的完整 Git 审查输入 | 随计划工作区删除；提交差异可由 Git 重新生成。 | 是否保留快照待定。 |
| `task-N-review.md`、`task-N-re-review.md` | 任务级双结论和逐条复审 | 原版完整 Reviewer 结论主要回到对话，账本记录摘要；没有强制保存这两类独立文件。 | 本地增加文件化复审；正式报告应汇总未解决发现，原件是否保留待定。 |
| 一次性探查脚本、临时 JSON/CSV、预览或特征摘要 | 调试与人工查看时可能生成，不是 SDD 固定产物 | 原版 SDD 没有针对这些科研临时材料的统一规则。 | 用毕删除；需要引用的证据先写入正式报告。 |
| `.pytest_cache/`、`__pycache__/`、`.pyc`、coverage 缓存 | pytest、Python 或覆盖率工具可能生成 | 原版 SDD 不规定这些语言或工具特定缓存的处理。 | 可再生缓存用毕删除；正式测试代码保留在 `scripts/pytest/`。 |
| PID、进度状态文件 | 长任务运行时可能生成 | 原版 SDD 不涉及科研长任务的 PID 管理。 | 仅作运行状态，集中到一个临时运行目录；结束后删除。 |
| 测试输出、冒烟结果、正式运行日志 | 命令和小样本运行可能产生 | 原版要求实现报告给出测试证据，最终分支收尾再跑完整测试；没有科研正式运行产物规范。 | 与纯缓存分开；有审计价值的命令、输入、结果和日志按功能单元约定保留。 |

**尚未确定：**在 Building Audit 被用户接受后，任务级报告、review diff、账本要全部删除、保留到 Runtime Finish，还是压缩归档。当前执行规则已暂缓自动删除，等待用户裁定。

## 7. 辅助 Skill 的边界与待确认事项

- `systematic-debugging/SKILL.md` 的价值是**根因尚不明或连续修复失败时的调查方法**；它不是额外一道 Audit Gate，也不替代正式报告。已知错误和确定修复方向时，可以直接按报告返工。待确认是否把它从 SDD 主路径完全降为按需工具。
- `receiving-code-review/SKILL.md` 教实现者核实技术反馈，不能自动替用户裁决 Building Audit。任务级审查已确定由 Agent 自动核实与返工，最多五轮；达到上限仍有实质问题则交用户决定。
- `verification-before-completion/SKILL.md` 应保留：每次声称“已修复／测试通过／审查完成”都需指明当前提交、实际运行命令、量化结果和未验证范围；它不证明科学方案本身正确。
- Building Audit 正式模板已按原版 `code-reviewer.md` 的输出格式重排，仍保留科研增补内容。用户明确裁决后由协调 Agent 更新 `Human Disposition`，不改写 Reviewer 原始发现；多轮报告用 `parent_audit_id` 关联。

## 8. Building 环节当前核查

| 核查点 | 当前结论 | 依据或剩余工作 |
|---|---|---|
| Proposal 批准后路由至 SDD；任务实现、TDD、独立任务 Review、最多五轮返工、整体独立 Review | 规则与引用已接通 | 根 `SKILL.md`、`references/build-stage.md`、SDD 主文件与各 Reviewer 提示词可互相定位；正式报告路径已切换为 Superpowers 排版模板。 |
| 最小功能单元的目录与证据边界 | 已补齐执行规则 | `references/build-stage.md` 明确核对五类顶层目录及本阶段所需子目录；`review-package` 前须处理冒烟产物的 Git 状态，不能丢弃审计证据。 |
| 正式 Building Audit 门禁 | 规则已写明 | 报告绑定 Spec、Plan、代码与审查证据；用户接受当前版本前不得进入 Runtime。新模板保留逐条人工裁决。 |
| Build Plan 的最后一个任务 brief | 已修复并定向验证 | `task-brief` 现在遇到同级或更高级的非 Task 标题便停止；用现有 Build Plan 模板运行其 AWK 提取逻辑，确认输出从 `Task 01` 开始且不包含后续“总体映射／批准”。 |
| SDD 工作区写入失败 | 已修复失控重试 | `sdd-workspace` 遇到创建目录失败会立即退出；受当前沙箱对 Git Bash 路径写入的限制，尚未完成正常写入路径的实跑。 |
| 技能结构与文档引用 | 已核对 | Skill 校验通过；本地 Markdown 链接检查无断链；相关 Bash 脚本语法检查通过。 |
| 完整 SDD 实战链条 | 未完成 | 尚未用获批准的真实 Build Plan 跑通实现、提交、任务 Review、返工、整体审查和用户门禁。 |

**仍待裁定：**SDD 临时材料的最终保留／删除条件。Task Review 的 Agent 自动闭环已由首次实际 Building 和用户确认；Building 与 Runtime 的承接规则仍需在正式运行中验证。
