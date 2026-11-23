import MathKernel.Workflow
import Mathlib.Data.Real.Basic

open MathKernel.Workflow

-- This deliberately failing check records why the first tasks use rationals.
noncomputable def realModel : Model where
  Input := ℝ
  Output := ℝ
  specification := fun x => x * x
  execute := fun _ x => x * x
  resources := fun _ => [⟨1, 24, 24⟩]
  feasible := fun _ => true
  formula := fun _ => "x * x"
  pseudocode := fun _ => "return x * x"

#eval (evaluationJson realModel (.object [("test", .int 1)])).compress
