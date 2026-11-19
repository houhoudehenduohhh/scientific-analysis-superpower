# Harness 与三层 Manifest 架构设计

## 设计目标

主对话使用自然语言，Subagent 负责研究与工程工作，Harness 负责把可执行的流程动作限制在当前状态允许的范围内。Harness 不替代科学判断，也不根据自然语言猜测科学结论。

## 三层 Manifest

三层 Manifest 单向引用，避免重复保存完整内容。

```text
analysis-state.json
├── 引用 Reader Spec / Build Plan
├── 引用 Building Manifest
└── 引用 Runtime Manifest

sdd/<plan-id>/manifest.json
└── 管理 SDD、Task Review、Fix Loop、Final Review 和 Building Audit

runtime/<run-id>/manifest.json
└── 管理 Runtime 步骤、节点审计、最终全链条审计和 Runtime Finish
```

### 主调度 Manifest

```json
{
  "phase": "proposal | building | building_audit | runtime | runtime_audit | runtime_finish",
  "status": "in_progress | waiting_user | blocked | complete",
  "reader_spec_sha256": "...",
  "build_plan_sha256": "...",
  "building_manifest": ".tmp/sdd/<plan-id>/manifest.json",
  "runtime_manifest": ".tmp/runtime/<run-id>/manifest.json",
  "next_allowed_actions": []
}
```

它只负责当前阶段、用户门禁、版本引用和下一步动作集合。

### Building Manifest

```json
{
  "phase": "building",
  "status": "fix_round_pending",
  "task_id": "T05",
  "tasks": {
    "T05": {
      "status": "fix_round_pending",
      "review_status": "CHANGES_REQUIRED",
      "fix_round": 1,
      "next_allowed_actions": ["dispatch_fix_agent"]
    }
  },
  "final_review": "pending",
  "building_audit": "blocked"
}
```

它只管理 SDD 任务状态和 Building Audit，不复制 Runtime 状态。

### Runtime Manifest

```json
{
  "phase": "runtime",
  "status": "milestone_audit_pending",
  "authorized_nodes": ["M01"],
  "steps": {
    "R01": {
      "status": "passed",
      "step_run_hash": "..."
    }
  },
  "milestone_audit": "pending",
  "final_chain_audit": "blocked"
}
```

它只管理 Runtime 步骤、节点审计和最终结果审计。

## 单一 Harness 脚本

对协调 Agent 暴露一个统一入口即可。内部实现可以拆成函数，但不再要求协调 Agent 直接调用多个状态脚本。

```text
sdd-harness.py init
sdd-harness.py status
sdd-harness.py allowed --action <action>
sdd-harness.py transition --to <state>
sdd-harness.py verify --artifact <path>
```

### 自然语言如何转成 Harness 动作

自然语言不直接改变 Manifest。协调 Agent 先把用户输入解释成一个候选动作，再由 Harness 检查该动作是否被当前状态允许。

```text
用户自然语言
  ↓
协调 Agent 识别意图和当前功能单元
  ↓
形成候选动作，例如 dispatch_fix_agent
  ↓
Harness 读取 Manifest 并检查动作
  ↓
允许：返回动作上下文和必需证据
拒绝：返回当前状态、拒绝原因和允许动作
  ↓
协调 Agent 才能派发 Subagent 或等待用户
```

Harness 不负责理解开放式科学语言。它只接受有限的动作枚举，并核对状态、版本和证据。这样可以避免把“继续修复”“继续运行”直接当成任意阶段跳转。

## Building 状态动作

```text
building_incomplete
  → resume_or_redispatch_implementer

task_review_pending
  → dispatch_task_reviewer

fix_round_pending
  → dispatch_fix_agent

re_review_pending
  → dispatch_reviewer

task_complete
  → dispatch_next_task 或 dispatch_final_review

final_review_pending
  → dispatch_final_review

building_audit_pending
  → create_building_audit

building_audit_gate
  → wait_for_user_decision
```

任何未列出的动作都拒绝。`CHANGES_REQUIRED` 在第五轮以前只能进入 `fix_round_pending`。

## Runtime 状态动作

```text
runtime_step_pending
  → execute_runtime_step

runtime_step_review_pending
  → dispatch_runtime_step_reviewer

runtime_fix_pending
  → retry_runtime_step 或 return_building 或 return_proposal

milestone_audit_pending
  → dispatch_milestone_audit

milestone_audit_gate
  → wait_for_user_decision

final_chain_audit_pending
  → dispatch_final_chain_audit

runtime_finish_pending
  → dispatch_runtime_finish
```

## Task 扩展

补充分析使用独立 Task ID，不能把父任务重新标记为完成：

```text
T05
T05-EXT01
T05-EXT02
```

Building Manifest 中记录：

```json
{
  "T05-EXT01": {
    "parent_task_id": "T05",
    "task_kind": "extension",
    "status": "task_review_pending",
    "task_spec_sha256": "...",
    "affected_tasks": ["T05", "T06"],
    "reusable_outputs": ["T03", "T04"],
    "invalidated_outputs": ["T05"],
    "next_allowed_actions": ["dispatch_implementer"]
  }
}
```

扩展 Task 必须明确继承约束、影响范围、可复用产物和必须重跑的下游。父任务和扩展任务分别审查、分别记录和分别进入 Runtime。

## 设计边界

Harness 只检查状态、证据、身份和合法动作。它不判断算法、科学口径、统计方法或结果解释。Subagent 负责实现、测试、审查和修复，用户负责 Spec Gate、Building Audit Gate、Runtime Audit Gate 以及五轮后未解决问题的裁决。

## 当前实现与后续方向

当前 Harness 已有固定状态转移脚本和 Building/fix loop 检查。后续应把状态、版本引用、Task 证据和 `next_allowed_actions` 合并到统一的 `sdd-harness.py` 入口。只有 Harness 成功返回允许动作，协调 Agent 才能派发下一步。
