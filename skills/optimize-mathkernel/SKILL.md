---
name: optimize-mathkernel
description: Find and verify cheaper mathematical plans for MathKernel three-matrix-chain tasks using the project's hardware cost model and Lean verifier.
---

# Optimize a MathKernel plan

Run commands from the project root. Read the supplied task and
[workflow](../../workflows/prove-improvement.md). The first model supports
`(AB)C` and `A(BC)` with one rectangular tile configuration shared by both GEMMs.

Use `inspect` to understand shapes, the baseline, and hardware limits. Propose
candidate JSON files with `order` (`left` or `right`) and positive integer
`tile.m`, `tile.n`, `tile.k`. Every GEMM dimension must be divisible by the
corresponding tile size. Three tile buffers share the specified fast memory.

Use `evaluate` to explore changes in association and tiling. Compare estimated
time, not arithmetic intensity alone. Both GEMMs run sequentially; their
individual ideal Roofline times are added. Do not change the task or model to
make a proposal pass.

For a visual comparison, use the plotting environment's Python to run
`tools/mathkernel.py roofline TASK CANDIDATE --output PREFIX`. It exports a PNG
image and point data. Coordinates can coincide when work and traffic decrease
proportionally; use the companion time comparison to assess that improvement.

Use `verify` for promising candidates. It generates an instance-bound Lean proof
from the verified transformation library, checks its axioms, and saves task,
candidate, proof, diagnostics, and result under `runs/`. Existing association
and scheduling rules do not require the agent to rewrite their proofs. A new
operator or execution rule requires extending and reviewing the Lean model.

Use `report` after `verify` exits zero with `verification_status: verified`.
Deliver the candidate, resource and modeled-time comparison, and artifact directory.

If verification fails, use `lean.log` to resolve the error or adjust the candidate.
Work within the task's search/time budget and preserve the best verified result.
