# MathKernel agent instructions

Use [skills/optimize-mathkernel/SKILL.md](skills/optimize-mathkernel/SKILL.md)
when asked to optimize a mathematical plan. Follow
[workflows/prove-improvement.md](workflows/prove-improvement.md) for the experiment.

- The task workflow accepts built-in or task-local Lean models. Matrix-chain
  association and elementwise fusion are examples, not a kernel-type boundary.
- Missing information or model definitions require explicit user authorization
  before agent supplementation. Present the completed specification and assumptions
  for user confirmation before recording `task confirm` and starting optimization.
- Preserve confirmed task/model/baseline/hardware/objective/budget inputs. Changes
  require renewed confirmation and fresh evidence. Confirmation files record real
  user decisions; agents must not invent them.
- Treat the supplied task, baseline, model definitions, and hardware parameters
  as the specification. Change them only when the task explicitly requests it.
- Evaluate proposals using `python3 tools/mathkernel.py`. Only Lean verification
  establishes `verification_status: verified`; task deliverables additionally need
  `acceptance_status: accepted` from fresh acceptance.
- Keep task candidates and verification records in the task workspace. Legacy
  standalone verification continues to use `runs/`.
- Use `mathkernel.paths.scratch_directory()` for temporary files. It respects
  `TMPDIR` and otherwise uses the project's `.cache/mathkernel` directory.
- Run `python3 -m unittest discover -s tests -v` for changes to tools or models.
  With Lean installed, this includes actual proof success and failure cases.
- Editing Lean model sources changes the trusted model. Rebuild and reverify;
  never present old verification artifacts as results for the changed model.
