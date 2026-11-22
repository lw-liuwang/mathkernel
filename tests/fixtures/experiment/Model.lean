import MathKernel.Workflow

-- Synthetic protocol fixture: counts exercise the acceptance contract, not a kernel model.
namespace MathKernel.TaskModel
open Workflow

def model (task : Value) : Model :=
  let scale := ((task.get "parameters").get "scale").nat
  {
    Input := Nat
    Output := Nat
    specification := fun x => x + 2
    execute := fun plan x =>
      if (plan.get "strategy").text == "compact" then x + 2
      else if (plan.get "strategy").text == "incorrect" then x + 3
      else (x + 1) + 1
    resources := fun plan =>
      if (plan.get "strategy").text == "compact" then [⟨2 * scale, 4 * scale, 8⟩]
      else [⟨2 * scale, 4 * scale, 8⟩, ⟨2 * scale, 4 * scale, 8⟩]
    feasible := fun plan => scale > 0 && (plan.get "strategy").text != "infeasible"
    formula := fun plan => if (plan.get "strategy").text == "compact" then "x + 2" else "(x + 1) + 1"
    pseudocode := fun plan => if (plan.get "strategy").text == "compact" then "return x + 2\n"
      else "t = x + 1\nreturn t + 1\n"
  }

end MathKernel.TaskModel
