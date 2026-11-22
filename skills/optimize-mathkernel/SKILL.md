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

The workflow is independent of a particular kernel. Reuse a suitable model or,
with authorization, add a task-local Lean model using the [task protocol](../../docs/tasks.md).
The matrix-chain and elementwise-fusion examples demonstrate two models. Preserve
the confirmed specification, model, baseline, hardware, objective and budget during
candidate iteration; changes need renewed user confirmation and fresh evidence.

Use `task evaluate TASK_DIRECTORY CANDIDATE` to record each proposal. Generate
candidates yourself or use an external agent; choose the search strategy for the
actual task. Use `task verify TASK_DIRECTORY ITERATION_ID` for promising candidates.
Custom models provide baseline and candidate correctness proofs; the tools bind
these to fixed feasibility, resource-count and improvement obligations. A successful
Lean invocation alone is insufficient. Diagnose failed attempts from their retained
logs. `task status` reports budget use and the best verified iteration.

Stop when the agreed target is met or the budget is exhausted. Use `task accept`
and `task export` for the selected iteration. Deliver the accepted bundle with
its scheme, before/after formulas, execution pseudocode, modeled Roofline PNG,
cost comparison, assumptions and proof evidence. If no candidate passes, report
the explored scope and unresolved obligations using the saved workspace.

For existing standalone matrix-chain task files, the legacy `inspect`, `evaluate`,
`verify`, `report` and `roofline` commands remain available. Use the task workflow
when confirmation, iteration tracking and bundle acceptance are required.
