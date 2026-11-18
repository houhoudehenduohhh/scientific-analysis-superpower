# Runtime Audit：独立结果审查

Runtime Report 是执行者的事实记录。本阶段由**一名未负责该次正式运行的独立 Reviewer** 审查运行及正式结果，形成可追溯裁决建议；最终是否接受由用户决定。

Runtime 有两类正式审计：Build Plan 指定的**阶段性验收节点审计**和全部节点接受后的**最终全链条结果审计**。节点内每步另有自动 Task Review，最多五轮修复复审；这些内部记录不是用户门禁。节点审计必须人工接受，接受一个节点不自动授权运行未包含的后续步骤。最后节点的审计不能代替最终全链条审计。

## 审查输入与范围

按[阶段模型规则](model-selection.md)显式派发节点和最终全链条 Reviewer，包括修复后的复审。

读取当前已批准的 Reader Spec、Build Plan、已接受的 Building Audit、`audits/runtime/report/` 中当前 Runtime Report、实际配置与日志、输入身份、正式结果和既往相关 Runtime Audit。用 [审查提示词](../templates/runtime-auditor-prompt.md) 和 [报告模板](../templates/runtime-audit-report.md)。Reviewer 只写审计报告，不修改源数据、代码、配置或结果，也不自行重跑正式生产任务。

节点审计先核对该节点全部步骤的独立审查、五轮内返工记录、逐 AC 状态、前置节点身份及跨任务交接。初审及最多一次针对已批准运行条件的集中修复与局部复审先存 `.tmp/runtime/<node_id>/`；这不是正式报告，也没有 `runtime_audit_id`。代码或科学方案修复按返回阶段及其门禁处理，不能借集中修复跨过 Building/Proposal。循环结束后才形成一份正式节点报告并停下。未关闭实质问题记 `CHANGES_REQUIRED` 或 `BLOCKED`，不能强行生成通过裁决。

最终全链条审计核对所有已接受节点的审计 ID 与 `run_hash`、`chain_hash`、跨节点接口/版本一致性、最终结果和科学解释边界。初审和最多一次针对已批准范围的集中修复／局部复审同样先留在 `.tmp/runtime/final_chain/`；需改代码或科学方案时返回相应上游门禁。然后生成另一份正式报告并停在用户门禁。不把各节点的局部 PASS 自动合成整体 PASS。

至少核对：运行的 `run_hash`、代码提交、Building `audit_id`、实际输入、配置与输出清单能否一一对应；运行是否完整，有无失败、重试、旧缓存或混合版本；输出 schema、单位/分母、数量、缺失、数值界限及适用的诊断是否符合批准方案；结果解释是否超出 Reader Spec 的结论边界。只对适用项作判断，并明确未验证范围。进程退出码或 pytest 通过不能代替结果审计；结果出乎预期也不能自动认定为错误。

## 发现分类与返回

| 核实后的原因 | 返回路径 |
|---|---|
| 运行环境、获准参数范围内的配置、缓存、输入绑定或部分失败；代码与科学方案仍适用 | Runtime：修正条件、重新运行，形成新 `run_hash` 并再次审计。 |
| 算法转代码、接口、调度、性能或恢复逻辑需要代码改动 | Building：补测试并修复；新提交重过 Building Audit，获准后重跑。 |
| 源数据资格、目标量、统计方法、概念算法或结论边界需要改变 | Proposal：修订 Reader Spec 和受影响 Build Plan，重新获批后再推进。 |
| 结果符合方案、证据完整，虽不理想但没有已证实缺陷 | 明确限制或解释边界，可提出新的 Proposal；不为迎合预期静默改分析。 |

重大未证实问题记为 `BLOCKED` 或 `CHANGES_REQUIRED`，不得用“以后再看”放行；非阻断限制列入 `PASS_WITH_NOTES` 供用户裁定。审计建议与用户讨论后的修复方向在正式报告中按 `finding_id` 逐条关联；未裁定的建议不是修复授权。

## 产物与门禁

在 `audits/runtime/` 生成与节点 `run_hash` 或最终 `chain_hash` 绑定的 Markdown 报告，例如 `audits/runtime/001_YYYYMMDD_<runtime_audit_id前12位>.md`。标明 `audit_scope: milestone | final_chain`、节点与步骤集合、完整 `runtime_audit_id`、上游审计 ID、Spec/Plan/Building Audit 指纹、发现与返回阶段、审查结论和 `audit_user_decision: pending`。多轮审计用序号和日期区分；旧报告保留，不能把新运行写成旧报告的结果。

正式报告生成后**停止**。节点报告只有结论为 `PASS`，或用户明确接受限制的 `PASS_WITH_NOTES`，且用户在看到报告后的后续消息接受本次 `runtime_audit_id` 与 `run_hash`，才解锁依赖节点；新节点还须在明确授权范围内。最终全链条报告在用户接受当前 `runtime_audit_id`、`chain_hash` 和限制后才许可 Runtime Finish。若用户决定修复，按返回路径处理；新 `run_hash` 使受影响节点及其下游许可失效，未受影响上游可核验后复用。
