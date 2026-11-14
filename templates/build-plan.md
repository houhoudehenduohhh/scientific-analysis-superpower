# Build Plan（构建计划）

> 在 Proposal 编写，获批后供 Building 执行。任务级 brief、进度文件和任务审查记录放在临时工作目录。

## 目标

- status: draft
- 对应的 Reader Spec 及版本或指纹：
- 构建目标：
- 不运行生产数据的边界：

## 工程实现与契约

- 工程实现顺序、关键组件职责和依赖：
- 输入校验、输出结构、关键接口与不变量：
- 失败行为和复现所需的入口、配置与记录：
- 计算成本、效率取舍及资源或恢复设计（按需）：

## 拟创建的脚本结构

先确定预计创建或修改的文件、模块职责和接口，再切分任务。`build/` 内部按实际任务细分。

```text
scripts/
├── build/                        # 主脚本；内部结构按本次实现自行规划
├── config/                       # 配置和配置指纹
├── pytest/                       # pytest 测试代码与必要的测试记录
├── smoke_test/                   # 小样本运行脚本与验证入口
└── logs/                         # 正式日志；runtime/ 子目录存临时运行状态
```

这五个一级目录是脚本区的统一边界；具体脚本树是本次规划结果，不是固定模板。`scripts/smoke_test/` 存验证代码，`results/smoke_test/` 存验证结果。PID、进度和恢复状态共用 `scripts/logs/runtime/`，结束后按运行规则清理。

| 脚本/模块 | 职责 | 输入 | 输出 | 对应实现契约 | 对应任务 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

## 全局约束摘录

只摘录各任务共同依赖的约束，并引用 Reader Spec 对应条目。

## 任务清单

Proposal 中先定义文件职责与接口，再划分可独立测试和验收的任务。能单独批准或拒绝的交付可以拆开，紧密依赖的配置、实现与测试归入同一任务。用户批准任务边界和依赖顺序后，Building 按计划执行。执行中需要实质调整边界时，更新本计划并提交用户裁决。

### Task 01：

**Files**

- Create:
- Modify:
- Test:

**Interfaces**

- Consumes:
- Produces:

**Task-local contract**

- 行为：
- 主要风险：
- 验收断言：
- 失败条件：
- 依赖的任务、Reader Spec 条目和本计划的实现契约：

**TDD steps**

- [ ] RED：写最小失败测试，列出关键输入与断言
- [ ] RUN：填写实际测试命令与预期失败原因
- [ ] GREEN：写最小实现
- [ ] RUN：填写任务测试、回归命令与预期结果
- [ ] REFACTOR：全绿后清理并再次运行全套测试
- [ ] REVIEW：提交 task brief、task report、diff 和测试证据给 Reviewer

## Build 总体映射

Proposal 填写拟覆盖的要求、任务、文件和验证方法。Building 补记实际证据。

| Reader Spec 要求或实现契约 | 任务 | 代码位置 | 验证方法或测试证据 | 未解决问题 |
|---|---|---|---|---|
|  |  |  |  |  |

## 批准

- decision: pending（pending / approved / rejected）
- approved_by：
- approved_at：
