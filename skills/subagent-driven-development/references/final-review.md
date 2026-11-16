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
the per-task human reports, and final test and smoke-check records. Ask this
one reviewer to trace
requirements through tasks, code, and evidence; check scientific and
cross-task fidelity; and write the initial technical review to
`<workspace>/final-review-initial.md`. This is SDD working evidence, not a
formal Building Audit: do not assign it an `audit_id`, write it under
`audits/building/`, or use it to request Runtime authorization. A code-quality
verdict alone is not the scientific Building Audit.

If the initial review finds implementation defects fixable within the
approved Reader Spec and Build Plan, dispatch ONE fix subagent with the
complete findings list — not one fixer per finding. Per-finding fixers each
rebuild context and re-run suites; a real session's final-review fix wave
cost more than all its tasks combined. Then run exactly one scoped re-review
of the fix wave (`bash scripts/review-package PLAN_FILE FIX_BASE HEAD` by its
absolute path, from the working tree you're executing in, over the fix
range, [re-review-prompt.md](../re-review-prompt.md)); save the re-review in
the same SDD workspace. This is the only automatic whole-branch fix wave.
If the finding requires a material scientific or Build Plan decision, do
not auto-fix it; carry it to the formal report for user decision. Record
residual findings as in the fix loop's breaker ([fix-loop.md](fix-loop.md)).
A substantive finding still open after re-review remains `BLOCKED` or
`CHANGES_REQUIRED`; no second automatic fix wave.

### Finish

After a clean initial review, or after the one fix wave and scoped re-review,
reconcile every human task report against the final reviewed `HEAD`. Update
reports for tasks affected by the whole-branch fix wave, including changed
AC evidence or residual limitations; retain the approved AC wording and
identify any condition still awaiting Runtime. Check that every Build Plan
task has a report and every AC has a status supported by the technical task
report and independent review. Include the reports in the formal reviewer's
evidence; an inconsistent or missing report is a documentation finding, not
permission to claim the task complete.

Then have an independent reviewer synthesize ONE formal report using the
[Building Audit template](../../../templates/building-audit-report.md) under
the functional unit's `audits/building/`. Include the initial review, any
fix and re-review evidence, every ledger `Ruling:`, deferred finding, and
open issue with its cost if wrong. Record the Reader Spec and Build Plan
hashes, current reviewed code commit, full branch and fix diff ranges where
applicable, and `audit_user_decision: pending`. If science/plan decisions or
substantive defects remain, report `BLOCKED` or `CHANGES_REQUIRED`; do not
claim acceptance. The creation of this formal report is the Building Audit
Gate: present it and STOP for the user's decision on this exact version.
Never auto-fix after a formal report with pending user decision. Do not
merge, delete the temporary workspace, or start Runtime in the same turn.
Retention and deletion of the temporary workspace still await the user's
decision; do not clean it up automatically after audit acceptance.
