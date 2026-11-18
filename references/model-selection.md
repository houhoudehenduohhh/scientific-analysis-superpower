# 阶段模型与推理档位

Codex 默认使用 GPT-6.2 Sol（工具模型 ID：`gpt-6.2-sol`）。每次派发子 Agent 时显式传入 `model` 和 `reasoning_effort`，包括修复和复审。若客户端无法使用推荐模型或档位，采用当前可用的接近选项，并在任务记录中注明实际设置或继承情况。

| 阶段 | 默认推理档位 | 升档条件 |
|---|---|---|
| Proposal（Reader Spec、Build Plan） | `high` | |
| Building 单任务实现及局部修复 | `low` | 跨模块集成或难以复现的问题用 `medium` |
| Task Review、局部 Re-review | `low` | 涉及统计口径、并发或跨模块影响时用 `medium` |
| Runtime 执行及步骤审查 | `low` | 异常根因不明时用 `medium` |
| 整体 Building Review、节点 Runtime Audit、最终全链条审计及其复审 | `medium` | 关键证据冲突或科学解释存在实质疑问时用 `high` |

主会话负责 Proposal 或 Runtime 执行时，由用户在 Codex 会话设置选择对应档位。Skill 的派发规则作用于新派发的子 Agent。

Building 进入第 4–5 轮修复时，按现有流程派新实现者，推理档位比卡住的实现者提高一级（`low` → `medium` → `high`，最高 `high`）。档位选择与独立审查、验收证据和门禁分别核对。
