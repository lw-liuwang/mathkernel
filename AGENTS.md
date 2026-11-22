# MathKernel agent instructions

Use [skills/optimize-mathkernel/SKILL.md](skills/optimize-mathkernel/SKILL.md)
when asked to optimize a mathematical plan. Follow
[workflows/prove-improvement.md](workflows/prove-improvement.md) for the experiment.

- The first implementation supports exactly three real matrices and left/right
  association with rectangular, exactly divisible output-stationary tiles.
- Treat the supplied task, baseline, model definitions, and hardware parameters
  as the specification. Change them only when the task explicitly requests it.
- Evaluate proposals using `python3 tools/mathkernel.py`; only `verify` can
  establish `verification_status: verified`.
- Keep alternative candidates and generated verification records in `runs/`.
- Use `mathkernel.paths.scratch_directory()` for temporary files. It respects
  `TMPDIR` and otherwise uses the project's `.cache/mathkernel` directory.
- Run `python3 -m unittest discover -s tests -v` for changes to tools or models.
  With Lean installed, this includes actual proof success and failure cases.
- Editing Lean model sources changes the trusted model. Rebuild and reverify;
  never present old verification artifacts as results for the changed model.
