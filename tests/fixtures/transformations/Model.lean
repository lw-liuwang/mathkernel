import MathKernel.Workflow

-- Synthetic semantics and arbitrary counts isolate the transformation protocol.
namespace MathKernel.TaskModel
open Workflow

def executePlan (_ : Value) (x : Nat) : Nat := x + 2

def setPasses (plan arguments : Value) : Except String Value :=
  if (plan.get "passes").nat == 0 then
    .error "The input plan must have positive passes"
  else
    match arguments with
    | .object [("passes", .int count)] =>
      if count > 0 then
        .ok (.object [("strategy", .str "scheduled"), ("passes", .int count)])
      else .error "passes must be a positive integer"
    | _ => .error "Expected exactly one integer argument: passes"

def setPassesRule : Transformation executePlan where
  name := "set_passes"
  description := "Set passes using {\"passes\": N}, with integer N > 0 and a positive input passes count."
  apply := setPasses
  sound := by
    intro plan arguments result _ x
    rfl

def model (task : Value) : Model :=
  let scale := ((task.get "parameters").get "scale").nat
  {
    Input := Nat
    Output := Nat
    specification := fun x => x + 2
    execute := executePlan
    resources := fun plan =>
      let passes := (plan.get "passes").nat
      [⟨passes * scale, 4 * passes * scale, if passes == 1 then 128 else 8⟩]
    feasible := fun plan => (plan.get "passes").nat > 0
    formula := fun plan => s!"x + 2 [passes={(plan.get "passes").nat}]"
    pseudocode := fun plan => s!"execute {(plan.get "passes").nat} synthetic passes; return x + 2\n"
    transformations := [setPassesRule]
  }

end MathKernel.TaskModel
