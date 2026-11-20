# Final Review and Finish

Part of the project's subagent-driven-development workflow. Every task in the plan is
complete.

The final whole-branch review gets a package too: run
`bash scripts/review-package PLAN_FILE MERGE_BASE HEAD` by its absolute path,
from the working tree you're executing in (MERGE_BASE = the commit the
branch started from, e.g. `git merge-base main HEAD`) and include the
printed path in the final review dispatch, so the final reviewer reads
one file instead of re-deriving the branch diff with git commands. Dispatch
with model `gpt-6.2-sol` and reasoning effort `medium` as creation arguments, using
[Building Auditor prompt](../../../templates/building-auditor-prompt.md) in initial-review mode. Point it at
the ledger's deferred-minor and parked lines so it can triage which must be
fixed before user acceptance.
For scientific analysis, also provide the approved Build Plan, Task MD files,
task review summary, source-data identity and qualification evidence,
the per-task technical reports, and final test and smoke-check records. Ask this
one reviewer to trace
requirements through tasks, code, and evidence; check scientific and
cross-task fidelity; and write the initial technical review to
`<workspace>/final-review-initial.md`. This is SDD working evidence, not a
formal Building Audit: do not assign it an `audit_id`, write it under
`audits/building/`, or use it to request Runtime authorization. A code-quality
verdict alone is not the scientific Building Audit.

If the initial review finds implementation defects fixable within the
approved Build Plan, dispatch ONE fix subagent with model `gpt-6.2-sol` and reasoning effort `low` and give it the
complete findings list — not one fixer per finding. Per-finding fixers each
rebuild context and re-run suites; a real session's final-review fix wave
cost more than all its tasks combined. Then run exactly one scoped re-review
of the fix wave (`bash scripts/review-package PLAN_FILE FIX_BASE HEAD` by its
absolute path, from the working tree you're executing in, over the fix
range, [re-review-prompt.md](../re-review-prompt.md)); save the re-review in
the same SDD workspace as `final-review-rereview.md`. Use the template's whole-branch
mode. The first heading is `# Overall Review`, followed by separate
`HEAD: <full post-fix commit SHA>` and `Verdict: PASS` or
`Verdict: CHANGES_REQUIRED` lines. Register this current-HEAD report as the
evidence for `building_audit_pending` and retain the initial review in the
evidence package. Without a fix wave, register the initial review for the
current HEAD. This is the only automatic whole-branch fix wave.
If the finding requires a material scientific or Build Plan decision, do
not auto-fix it; carry it to the formal report for user decision. Record
residual findings as in the fix loop's breaker ([fix-loop.md](fix-loop.md)).
If the overall review still finds a substantive issue, record
`Verdict: CHANGES_REQUIRED` and submit a `BLOCKED` or `CHANGES_REQUIRED`
formal Building Audit for the user's decision. The automatic fix wave is limited
to one round.

### Finish

After a clean initial review, or after the one fix wave and scoped re-review,
verify that the technical task reports and independent reviews cover all
approved tasks and ACs. Use any whole-branch repair and re-review evidence to
record changed validations and remaining limits at the final reviewed `HEAD`.
Provide the formal auditor with the complete evidence for the task acceptance
index. The index uses one row per approved AC and carries the Task MD purpose and
success criterion, the current verdict, the behavior verified, and outstanding
verification. Mark any condition that awaits Runtime.

Have an independent reviewer use the Building Auditor prompt in formal-audit mode to synthesize ONE report. If dispatching a
reviewer for synthesis, pass model `gpt-6.2-sol` and reasoning effort
`medium` as creation arguments. Use the
[Building Audit template](../../../templates/building-audit-report.md) under
the functional unit's `audits/building/`. Include the initial review, any
fix and re-review evidence, every ledger `Ruling:`, deferred finding, and
open issue with its cost if wrong. Record the Build Plan and Task MD hashes,
current reviewed code commit, full branch and fix diff ranges where
applicable, and `audit_user_decision: pending`. If science/plan decisions or
substantive defects remain, report `BLOCKED` or `CHANGES_REQUIRED`; do not
claim acceptance. The creation of this formal report is the Building Audit
Gate: present it and STOP for the user's decision on this exact version.
Never auto-fix after a formal report with pending user decision. Do not
merge, delete the temporary workspace, or start Runtime in the same turn.
Keep the SDD workspace after audit acceptance for Agent review and recovery.

For an extension, trace the whole affected chain against the current Build Plan, approved Task MDs and branch diff. Identify changed interfaces, replacement outputs, relevant regression evidence, and which prior approvals or outputs can be reused after identity checks. Record scope and Task MD identities in the formal report.
