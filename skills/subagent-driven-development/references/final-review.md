# Final Review and Finish

Part of superpowers:subagent-driven-development. Every task in the plan is
complete.

The final whole-branch review gets a package too: run
`bash scripts/review-package PLAN_FILE MERGE_BASE HEAD` by its absolute path,
from the working tree you're executing in (MERGE_BASE = the commit the
branch started from, e.g. `git merge-base main HEAD`) and include the
printed path in the final review dispatch, so the final reviewer reads
one file instead of re-deriving the branch diff with git commands. Dispatch
on the most capable available model (see SKILL.md's Model Selection), using
[code-reviewer.md](../../requesting-code-review/code-reviewer.md). Point it at
the ledger's deferred-minor and parked lines so it can triage which must be
fixed before user acceptance.
For scientific analysis, also provide the approved Reader Spec and Build
Plan, task review summary, source-data identity and qualification evidence,
and final test and smoke-check records. Ask this one reviewer to trace
requirements through tasks, code, and evidence; check scientific and
cross-task fidelity; and write one report using
[Building Audit template](../../../templates/building-audit-report.md) under
the functional unit's `audits/building/`. A code-quality verdict alone is
not the scientific Building Audit.

If the final whole-branch review returns findings, dispatch ONE fix subagent
with the complete findings list — not one fixer per finding.
Per-finding fixers each rebuild context and re-run suites; a real
session's final-review fix wave cost more than all its tasks combined.
Then run exactly one scoped re-review of the fix wave
(`bash scripts/review-package PLAN_FILE FIX_BASE HEAD` by its absolute path,
from the working tree you're executing in, over the fix range,
[re-review-prompt.md](../re-review-prompt.md)).
Record residual findings as in the fix loop's breaker
([fix-loop.md](fix-loop.md)). Non-blocking limitations remain explicit in
the audit report for user decision. A substantive or load-bearing finding
keeps the report at `BLOCKED` or `CHANGES_REQUIRED`; do not mark the
implementation accepted. There is no second automatic fix wave.

### Finish

Before stopping, carry every ledger `Ruling:`, deferred finding, and open
issue into the Building Audit report, with its evidence and cost if wrong.
Record the Reader Spec and Build Plan hashes, the reviewed code commit,
the diff range, and `audit_user_decision: pending`. Present the report and
stop for the user's decision on this exact version. Do not merge, delete
the temporary workspace, or start Runtime in the same turn. Retention and
deletion of the temporary workspace are still awaiting the user's decision;
do not clean it up automatically after audit acceptance.
