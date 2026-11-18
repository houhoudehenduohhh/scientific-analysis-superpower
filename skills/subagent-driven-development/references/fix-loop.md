# The Fix Loop

Part of superpowers:subagent-driven-development. The task review reported
spec ❌, a Critical or Important finding, or a ⚠️ item you confirmed as a real
gap.

Before the loop starts, two routes leave it immediately:

- Record Minor findings in the progress ledger as you go
  (`Task <N>: minor (deferred): <one-liner>`), and point the final
  whole-branch review at that list so it can triage which must be fixed
  before user acceptance. A roll-up nobody reads is a silent discard. Minor findings
  never enter the loop.
- A finding labeled plan-mandated — or any finding that conflicts with
  what the plan's text requires — requires a recorded ruling against the
  approved Spec. If correcting it materially changes the scientific design
  or Build Plan, pause for user decision. Do not dismiss the finding because
  the plan mandates it or dispatch a contradictory fix silently.
Everything else enters the loop. A fix round is one fix dispatch plus one
scoped re-review. Five rounds maximum per task:

**Rounds 1-3 — resume the original implementer.** Send it the open findings
verbatim. Its context is intact: it knows the task, the code, and its own
choices. If your harness cannot send another message to a live subagent,
dispatch a fresh implementer carrying the brief path, the report-file path,
and the findings — the report file is the persistent memory either way.

**Rounds 4-5 — dispatch a fresh implementer with the same fixed creation arguments as the original implementer** (see [implementer prompt](../implementer-prompt.md)), with the brief path, the report-file path, the open
findings, and this framing: "A prior implementer attempted this task
[N] times; you own it now. Read the report file for what was tried." A loop
that survives three resumes usually means the implementer cannot see its
own problem — fresh eyes and a capability bump in one move.

**Every round, either way:** the implementer fixes, re-runs the tests
covering the amended code, appends its fix report to the same report file,
and returns the short contract. Before re-dispatching the reviewer, confirm
the fix report contains the covering tests, the command run, and the
output; dispatch the re-review once all three are present. Name the
covering test files in the fix message — a one-line fix does not need the
whole suite.

**The re-review is scoped.** Run `bash scripts/review-package PLAN_FILE FIX_BASE HEAD`
by its absolute path, from the working tree you're executing in, where FIX_BASE is the head the previous review saw, and dispatch
[re-review-prompt.md](../re-review-prompt.md) with the findings list, the
brief, the report file, and the printed diff path. The re-reviewer verdicts
each finding ADDRESSED or NOT ADDRESSED and flags new breakage in the fix
diff only. New Critical/Important breakage in the fix diff joins the open
findings list. Out-of-scope observations go to the ledger as deferred
minors — they never extend the loop.

**After each round,** append to the ledger:
`Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <finding one-liners>; commits <a7>..<b7>)`

Never fix findings yourself in the controller session — your context stays
clean for coordination, and controller fixes skip review.

**The breaker.** When round 5's re-review still leaves findings open, stop
dispatching. Record each open finding, its evidence, affected downstream
tasks, attempted fixes, and your assessment in the ledger:

- **Reviewer finding is unsupported:** record the counterevidence and
  disagreement for the final independent review; do not silently discard it.
- **Real but non-blocking:** carry it into the final Building Audit report
  with its impact and limitation for the user to accept or reject.
- **Real and substantive or load-bearing:** pause the dependent sequence.
  Present the ledger, code version, failed tests, review and re-review
  evidence to the user for a new implementation attempt, a plan/spec change,
  or another explicit decision. Do not mark the task complete.

Do not end a fix loop early by pre-judging the reviewer. Every disposition
is a ledger entry; a silent discard is forbidden.
