import MathKernel.Workflow

namespace MathKernel.TaskModel
open Workflow

def model (task : Value) : Model :=
  let n := ((task.get "parameters").get "length").nat
  let bytes := ((task.get "hardware").get "element_bytes").nat
  {
    Input := (Fin n → ℝ) × (Fin n → ℝ) × (Fin n → ℝ)
    Output := Fin n → ℝ
    specification := fun (x, a, b) i => (x i + a i) * b i
    execute := fun plan (x, a, b) =>
      if (plan.get "kind").text == "fused" then fun i => (x i + a i) * b i
      else let t := fun i => x i + a i; fun i => t i * b i
    resources := fun plan =>
      if (plan.get "kind").text == "fused" then [⟨2 * n, 4 * n * bytes, 4 * bytes⟩]
      else [⟨n, 3 * n * bytes, 4 * bytes⟩, ⟨n, 3 * n * bytes, 4 * bytes⟩]
    feasible := fun plan => n > 0 && ((plan.get "kind").text == "fused" || (plan.get "kind").text == "split")
    formula := fun plan => if (plan.get "kind").text == "fused" then "y[i] = (x[i] + a[i]) * b[i]"
      else "t[i] = x[i] + a[i]; y[i] = t[i] * b[i]"
    pseudocode := fun plan =>
      if (plan.get "kind").text == "fused" then
        s!"for i in 0..{n}:\n  load x[i], a[i], b[i]\n  tmp = x[i] + a[i]  # fast storage\n  store y[i] = tmp * b[i]\n"
      else s!"for i in 0..{n}: store t[i] = x[i] + a[i]\nfor i in 0..{n}: store y[i] = t[i] * b[i]\n"
  }

end MathKernel.TaskModel
