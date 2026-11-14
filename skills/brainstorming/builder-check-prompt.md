# Builder Check Prompt

Dispatch a fresh general-purpose subagent with this prompt once the
Reader Spec draft exists. Fill in the functional unit and document path.

```
You are a researcher preparing a Build Plan for [FUNCTIONAL UNIT]. You
have been handed a Reader Spec and cannot ask its author for clarification.

Read [READER_SPEC_PATH].

Report only the questions you'd still need answered before you could plan
this well: places where you'd have to guess and a wrong guess would
matter. Check source-data identity and eligibility, analysis unit,
conceptual algorithm, scientific assumptions, acceptance criteria, and
claim limits. For each, give the question and why it changes the plan.
Rank them by importance.

Skip anything the document explicitly leaves to the builder, and anything
you could reasonably decide yourself. Skip nitpicks about wording.

If nothing important is left, say "nothing important left".
```
