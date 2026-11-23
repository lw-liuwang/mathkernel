---
name: optimize-mathkernel
description: Prepare kernel optimization tasks, iterate mathematical transformations, and deliver Lean-verified MathKernel schemes with cost comparisons and Roofline plots. Use for existing or new kernels, including fusion and splitting.
---

# Optimize a MathKernel task

Read the repository [workflow](../../workflows/prove-improvement.md). Run tools
from the installed repository using the Python environment that has plotting
support. Start with `tools/mathkernel.py doctor` and `task check TASK_DIRECTORY`.

Gather the mathematical specification, input conditions, numerical semantics,
hardware resources, baseline execution plan, objective, constraints and iteration
budget. Help the user resolve the omissions reported by `check`. Request explicit
user authorization before supplying missing facts, model definitions or cost rules;
record the supplement, basis and scope. Present the completed specification and
model assumptions for user confirmation before optimization. `task confirm` records
an actual user decision; never fabricate it or copy a fixture's confirmation.

Each experiment supplies its own Lean definitions and proofs using the
[task protocol](../../docs/tasks.md). The repository provides the generic workflow
and proof contract. Request authorization before adding missing definitions. Preserve
the confirmed specification, model, baseline, hardware, objective and budget during
candidate iteration; changes need renewed user confirmation and fresh evidence.

If the model defines transformations, use `task rules TASK_DIRECTORY` to inspect
names and argument requirements. Rules are part of the confirmed model. Choose
rules and arguments to submit a `derivation` instead of a direct `plan`; the tools
apply the chain from the baseline and retain each successful step. Rule inspection
does not spend exploration budget or establish proof verification.

Use `task evaluate TASK_DIRECTORY CANDIDATE` to record each proposal. Generate
candidates yourself or use an external agent; choose the search strategy for the
actual task. Use `task verify TASK_DIRECTORY ITERATION_ID` for promising candidates.
Direct plans need baseline and candidate correctness proofs. Derivations need only
the reusable baseline proof; the tools compose candidate correctness from the
selected rules and recheck the saved trace. Intermediate costs may increase; the
final plan must meet feasibility and improvement obligations. A successful Lean
invocation alone is insufficient. For `rule_failed`, inspect `failed_step`, the
diagnostic and the retained partial trace before revising the chain. Each chain
evaluation spends one attempt, including rule failures and timeouts. `task status`
reports budget use and the best verified iteration.

Stop when the agreed target is met or the budget is exhausted. Use `task accept`
and `task export` for the selected iteration. Deliver the accepted bundle with
its scheme, before/after formulas, execution pseudocode, modeled Roofline PNG,
cost comparison, assumptions and proof evidence. If no candidate passes, report
the explored scope and unresolved obligations using the saved workspace.
