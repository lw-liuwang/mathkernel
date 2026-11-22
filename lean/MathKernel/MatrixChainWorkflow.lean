import MathKernel.Workflow

namespace MathKernel.MatrixChainWorkflow
open Workflow

def decode (value : Value) : Plan :=
  let tile := value.get "tile"
  ⟨if (value.get "order").text == "right" then .right else .left,
    ⟨(tile.get "m").nat, (tile.get "n").nat, (tile.get "k").nat⟩⟩

def model (task : Task) : Model where
  Input := Matrix (Fin task.m) (Fin task.k) ℝ ×
    Matrix (Fin task.k) (Fin task.n) ℝ × Matrix (Fin task.n) (Fin task.p) ℝ
  Output := Matrix (Fin task.m) (Fin task.p) ℝ
  specification := fun (a, b, c) => (a * b) * c
  execute := fun plan (a, b, c) => denote task (decode plan) a b c
  resources := fun plan => (gemms task (decode plan)).map
    (fun g => (gemmSchedule task.hardware (decode plan).tile g).cost)
  feasible := fun plan => validTask task && MathKernel.feasible task (decode plan)
  formula := fun plan => if (decode plan).order == .right then "Y = A(BC)" else "Y = (AB)C"
  pseudocode := fun plan =>
    let tile := (decode plan).tile
    let schedule := s!"output-stationary GEMM; tile=({tile.m}, {tile.n}, {tile.k}); materialize T in slow memory\n"
    schedule ++ if (decode plan).order == .right then "T = GEMM(B, C)\nY = GEMM(A, T)\n"
      else "T = GEMM(A, B)\nY = GEMM(T, C)\n"

theorem correct (task : Task) (plan : Value) :
    ∀ x, (model task).execute plan x = (model task).specification x := by
  intro ⟨a, b, c⟩
  change denote task (decode plan) a b c = (a * b) * c
  cases h : (decode plan).order <;> simp [denote, h, Matrix.mul_assoc]

end MathKernel.MatrixChainWorkflow
