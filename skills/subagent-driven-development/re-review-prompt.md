# Scoped Re-Review Prompt Template

Use this template when dispatching a re-review after a fix round. The
re-reviewer verifies the findings were addressed and checks the fix diff for
new breakage. It is not a fresh review — the full review already happened.

**Purpose:** Verify each finding from the previous review was addressed, and
that the fix itself broke nothing.

Pass the model and reasoning effort below as subagent creation arguments.
For an overall fix wave, use the same reviewer role and creation arguments in
whole-branch mode. Provide the Build Plan, initial Overall Review, scoped fix
package and full current HEAD in place of the single-task brief and task scope.

```
Subagent (general-purpose):
  description: "Re-review Task N fix round R"
  model: "gpt-6.2-sol"
  reasoning_effort: "low"
  prompt: |
    Scope: [Task fix round / whole-branch fix wave]. The Task fix round is
    the default. In whole-branch mode, read the Build Plan and original
    Overall Review where the template refers to the Task brief and findings.
    In either mode, verify each prior finding and inspect the scoped fix diff.

    ## The Task

    Read the task brief: [BRIEF_FILE] (approved task snapshot, including its full ID)

    ## The Findings Under Verification

    [FINDINGS]

    ## The Fix

    Read the immutable implementer report and the separate round-specific fix
    report:
    [REPORT_FILE]

    **Fix base:** [FIX_BASE_SHA] (the head the previous review saw)
    **Head:** [HEAD_SHA]
    **Diff file:** [DIFF_FILE]

    Read the diff file once — it contains the fix commits, a stat summary,
    and the fix diff with surrounding context. Do not re-run git commands.
    If the diff file is missing, fetch the diff yourself:
    `git diff --stat [FIX_BASE_SHA]..[HEAD_SHA]` and
    `git diff [FIX_BASE_SHA]..[HEAD_SHA]`.

    Your review is read-only on this checkout except for writing the
    re-review report to [RE_REVIEW_FILE] in the plan's temporary workspace.
    Do not mutate source files, the index, HEAD, or branch state.

    ## You Do Not Dispatch Subagents

    Do all of this review yourself. Never spawn a subagent to review part
    of the diff, and never spawn another reviewer for a second opinion.
    This process already provides every review seat the work gets; a
    reviewer you spawn duplicates one of them at full cost, and its
    verdict counts for nothing. If the diff feels too large for one
    pass, review it in passes yourself and say so in your report.

    ## Scope

    Your scope is the findings list and the fix diff. Verdict every finding.
    Inspect the fix diff for new problems the fix itself introduced. Do NOT
    re-review code the fix did not touch: if you notice an issue entirely
    outside the fix diff, report it under Out-of-Scope Observations — it
    does not block this task and does not extend the loop. A broad
    whole-branch review happens after all tasks are complete.

    ## Tests

    The implementer re-ran the tests covering the amended code and recorded
    the results in the separate immutable fix report. Treat the report as
    unverified claims:
    confirm the fix report names the covering tests and shows their output,
    and verify the claims against the diff. Do not re-run the suite to
    confirm their report. Run a test only when reading the code raises a
    specific doubt that no existing run answers — and then a focused test,
    never a package-wide suite.

    ## Output Format

    In whole-branch mode, start [RE_REVIEW_FILE] with `# Overall Review`,
    then write `HEAD: [HEAD_SHA]` with the full current commit, and either
    `Verdict: PASS` or `Verdict: CHANGES_REQUIRED`, each on its own line.
    Record finding dispositions and any new breakage within the fix scope.
    This is the current technical review evidence for Building Audit. Omit
    formal audit-gate fields, including an audit ID or user decision.

    In Task fix-round mode for scientific-analysis, write [RE_REVIEW_FILE] with the exact six
    headings from `templates/building-audit-report.md`, in that order. Put
    each ADDRESSED/NOT ADDRESSED verdict, new breakage, out-of-scope note,
    proposed resolution, and evidence in the applicable section. Do not use
    the generic Finding Verdicts/New Breakage/Out-of-Scope/Assessment schema
    as top-level headings. End with the template's audit-gate fields and keep
    user acceptance pending. Return only the round verdict, open findings,
    and report path in the final message. Include an exact machine-readable
    line `Verdict: PASS` or `Verdict: CHANGES_REQUIRED`. Keep this report
    immutable and create a new file for every later round.

    Within the six sections, identify each prior finding as ADDRESSED or NOT
    ADDRESSED with file:line evidence, record any new breakage and any
    out-of-scope observation, and state the fix-round verdict. "Attempted" is
    not addressed: the defect must no longer exist.
```

**Placeholders:**
- `[BRIEF_FILE]` — the task brief file (same file the implementer worked from)
- `[FINDINGS]` — the Critical/Important findings and spec gaps from the
  previous review, copied verbatim, one per bullet
- `[REPORT_FILE]` — the immutable implementer's report file
- `[FIX_REPORT_FILE]` — the immutable report for this fix round
- `[FIX_BASE_SHA]` — the head the previous review saw
- `[HEAD_SHA]` — current commit
- `[DIFF_FILE]` — the path `bash scripts/review-package PLAN_FILE FIX_BASE HEAD` printed
  (run by its absolute path, from the working tree you're executing in)
- `[RE_REVIEW_FILE]` — the scoped re-review report path in this plan's temporary workspace

**Re-reviewer returns:** per-finding verdicts (ADDRESSED / NOT ADDRESSED),
new breakage in the fix diff, out-of-scope observations, and a round verdict.
