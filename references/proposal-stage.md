# Proposal 阶段规则

Proposal 只负责讨论研究目标、源数据、边界和算法方向，并生成当前版本的 Build Plan 与 Task MD。它不生成代码、不运行正式分析、不进行审计。

## 输出

```text
specs/build_plan.md
specs/tasks/task-01/task-01.md
```

Build Plan 记录目标、源数据、算法概括、拟得到的输出、项目目录结构、任务清单、Runtime 执行图和阶段性验收节点。Task MD 记录一个任务的目的、边界、输入、脚本、输出、验收条件、验证证据和上下游影响。

## 执行顺序

1. 确定一个最小功能单元和写入位置。
2. 与用户讨论目标、源数据、边界、算法方向和输出。
3. 按模板生成或更新 Build Plan，在「目标与边界」写明 `功能单元 Git 根目录` 的绝对路径。若用户给的是上层目录，定位本轮实际开发的子目录。
4. 按模板生成本轮 Task MD，并在 Build Plan 中索引。
5. 运行 Harness 的 `verify-build-plan` 和带 `--build-plan BUILD_PLAN` 的 `verify-task-spec`。验明全部索引任务、AC、结构化路径和依赖图。
6. 检查任务依赖、接口、AC 和 Runtime 步骤图无环。
7. 呈现文件、版本指纹、校验结果和将初始化或复用 Git 的绝对路径，等待用户批准。更换该路径属于计划实质变更，须重新批准。

## 路径及验收节点

- 在 Build Plan 的「项目目录结构」声明 `- path_schema: 1`，用主入口表为每个任务登记路径和新增、既有或迁移类型。每个 Task MD 用「主入口路径」字段写同样的路径。无主入口的任务也须明确声明。
- 新增或迁移的主入口及新增分析实现模块使用 `scripts/build/`。迁移时记录受影响的调用方。配置、pytest、冒烟入口与日志分别使用 `scripts/config/`、`scripts/pytest/`、`scripts/smoke_test/` 和 `scripts/logs/`。
- 在 Build Plan 的「拟得到的输出」表填 `results/data/`、`results/plot/` 或 `results/smoke_test/` 下的逻辑文件路径。把读者需要的分组和文件名写入路径。运行与执行轮次的标识由 Harness 登记。
- 所有节点各自通过节点审计。全部节点获接受后开展独立全链条审计，包括只有一个节点的计划。
- 新计划的校验及初始化须通过结构化路径检查。已初始化且仍绑定同一批准版本的旧工作区可以恢复。旧计划若尚未初始化，使用当前结构补齐并取得对应版本批准。

## 门禁

只有当前 Build Plan 与本轮 Task MD 均通过 Harness 格式校验，并获得用户明确批准后，才能进入 Building。Proposal 期间只读检查仓库状态，Git 初始化留在 Building。

## 返回 Proposal

研究目标、源数据资格、概念算法、统计方法、关键假设或结论边界发生实质变化时，返回 Proposal，更新受影响的 Build Plan 和 Task MD，并重新获得批准。仅改变代码工程实现时返回 Building。

## 补充任务

补充任务在父任务目录下新增 Task MD，例如 `T01-EXT01` 对应 `specs/tasks/task-01/task-01-ext01.md`，并更新 Build Plan 任务清单。需要时标记受影响的下游任务和失效的旧结果。补充任务仍须经过 Harness 校验和用户批准，不能直接进入 Building 或 Runtime。
