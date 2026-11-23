import MathKernel.Workflow
import Mathlib.Data.Rat.Defs

namespace MathKernel.TaskModel
open Workflow

structure Inputs (n : Nat) where
  a : Fin n → Rat
  b : Fin n → Rat
  c : Fin n → Rat
  d : Fin n → Rat

def specification (n : Nat) (x : Inputs n) : Fin n → Rat :=
  fun i => (x.a i * x.b i + x.c i) * x.d i

def executePlan (n : Nat) (plan : Value) (x : Inputs n) : Fin n → Rat :=
  if (plan.get "strategy").text == "fused" then
    fun i => (x.a i * x.b i + x.c i) * x.d i
  else
    let first := fun i => x.a i * x.b i
    let second := fun i => first i + x.c i
    fun i => second i * x.d i

theorem execute_correct (n : Nat) (plan : Value) (x : Inputs n) :
    executePlan n plan x = specification n x := by
  unfold executePlan
  split <;> rfl

def fuse (plan arguments : Value) : Except String Value :=
  if (plan.get "strategy").text != "separate" then
    .error "fuse requires the three-pass separate baseline"
  else
    match arguments with
    | .object [] => .ok (.object [("strategy", .str "fused")])
    | _ => .error "fuse takes an empty arguments object"

def fuseRule (n : Nat) : Transformation (executePlan n) where
  name := "fuse"
  description := "Fuse three passes without changing arithmetic order; arguments: {}. Requires strategy=separate."
  apply := fuse
  sound := by
    intro plan arguments result _ x
    exact (execute_correct n result x).trans (execute_correct n plan x).symm

def model (task : Value) : Model :=
  let n := ((task.get "parameters").get "n").nat
  {
    Input := Inputs n
    Output := Fin n → Rat
    specification := specification n
    execute := executePlan n
    -- Count payload reads/writes; intermediate arrays reside in slow storage.
    resources := fun plan =>
      if (plan.get "strategy").text == "fused" then
        [⟨3 * n, 40 * n, 40⟩]
      else
        [⟨n, 24 * n, 24⟩, ⟨n, 24 * n, 24⟩, ⟨n, 24 * n, 24⟩]
    feasible := fun plan => n > 0 &&
      ((plan.get "strategy").text == "separate" || (plan.get "strategy").text == "fused")
    formula := fun plan => s!"y[i] = (a[i] * b[i] + c[i]) * d[i]; n={n}; strategy={(plan.get "strategy").text}"
    pseudocode := fun plan =>
      if (plan.get "strategy").text == "fused" then
        "for i: y[i] = (a[i] * b[i] + c[i]) * d[i]\n"
      else
        "for i: t1[i] = a[i] * b[i]\nfor i: t2[i] = t1[i] + c[i]\nfor i: y[i] = t2[i] * d[i]\n"
    transformations := [fuseRule n]
  }

end MathKernel.TaskModel
