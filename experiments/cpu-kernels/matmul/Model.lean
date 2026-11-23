import MathKernel.Workflow
import Mathlib.Data.Rat.Defs

namespace MathKernel.TaskModel
open Workflow

structure Inputs where
  a : Nat → Nat → Rat
  b : Nat → Nat → Rat

-- The first component is the current chunk; the second contains later chunks.
def chunkAux {α : Type} (width : Nat) : List α → Nat → List α × List (List α)
  | [], _ => ([], [])
  | x :: xs, 0 =>
    let rest := chunkAux width xs width
    ([], (x :: rest.1) :: rest.2)
  | x :: xs, remaining + 1 =>
    let rest := chunkAux width xs remaining
    (x :: rest.1, rest.2)

theorem chunkAux_flatten {α : Type} (width : Nat) (xs : List α) (remaining : Nat) :
    (chunkAux width xs remaining).1 ++ (chunkAux width xs remaining).2.flatten = xs := by
  induction xs generalizing remaining with
  | nil => rfl
  | cons x xs ih =>
    cases remaining with
    | zero => simpa [chunkAux] using congrArg (List.cons x) (ih width)
    | succ remaining => simpa [chunkAux] using congrArg (List.cons x) (ih remaining)

def chunks {α : Type} (block : Nat) : List α → List (List α)
  | [] => []
  | x :: xs =>
    let rest := chunkAux (block - 1) xs (block - 1)
    (x :: rest.1) :: rest.2

theorem chunks_flatten {α : Type} (block : Nat) (xs : List α) :
    (chunks block xs).flatten = xs := by
  cases xs with
  | nil => rfl
  | cons x xs =>
    simpa [chunks] using congrArg (List.cons x) (chunkAux_flatten (block - 1) xs (block - 1))

def dot (n : Nat) (x : Inputs) (i j : Nat) : Rat :=
  (List.range n).foldl (fun acc k => acc + x.a i k * x.b k j) 0

def tiledDot (n block : Nat) (x : Inputs) (i j : Nat) : Rat :=
  (chunks block (List.range n)).foldl
    (fun acc ks => ks.foldl (fun acc k => acc + x.a i k * x.b k j) acc) 0

theorem tiledDot_correct (n block : Nat) (x : Inputs) (i j : Nat) :
    tiledDot n block x i j = dot n x i j := by
  unfold tiledDot dot
  rw [← List.foldl_flatten, chunks_flatten]

def specification (n : Nat) (x : Inputs) : Fin n → Fin n → Rat :=
  fun i j => dot n x i.val j.val

def executePlan (n : Nat) (plan : Value) (x : Inputs) : Fin n → Fin n → Rat :=
  if (plan.get "strategy").text == "tiled" then
    fun i j => tiledDot n (plan.get "block").nat x i.val j.val
  else
    specification n x

theorem execute_correct (n : Nat) (plan : Value) (x : Inputs) :
    executePlan n plan x = specification n x := by
  unfold executePlan
  split
  · funext i j
    exact tiledDot_correct _ _ _ _ _
  · rfl

def tile (n : Nat) (plan arguments : Value) : Except String Value :=
  if (plan.get "strategy").text != "naive" && (plan.get "strategy").text != "tiled" then
    .error "tile requires strategy=naive or tiled"
  else
    match arguments with
    | .object [("block", .int block)] =>
      if block > 0 && block.toNat ≤ n then
        .ok (.object [("strategy", .str "tiled"), ("block", .int block)])
      else .error "block must be between 1 and n"
    | _ => .error "Expected exactly one integer argument: block"

def tileRule (n : Nat) : Transformation (executePlan n) where
  name := "tile"
  description := "Tile i,j,k with increasing k per output; arguments: {block: integer in [1,n]}. Fast-memory feasibility is checked separately."
  apply := tile n
  sound := by
    intro plan arguments result _ x
    exact (execute_correct n result x).trans (execute_correct n plan x).symm

def model (task : Value) : Model :=
  let n := ((task.get "parameters").get "n").nat
  {
    Input := Inputs
    Output := Fin n → Fin n → Rat
    specification := specification n
    execute := executePlan n
    -- Ideal two-level payload traffic: each A/B tile is loaded once per C tile.
    resources := fun plan =>
      if (plan.get "strategy").text == "tiled" then
        let block := (plan.get "block").nat
        let tiles := (n + block - 1) / block
        [⟨2 * n * n * n, 16 * n * n * tiles + 8 * n * n, 24 * block * block⟩]
      else
        [⟨2 * n * n * n, 16 * n * n * n + 8 * n * n, 24⟩]
    feasible := fun plan => n > 0 &&
      ((plan.get "strategy").text == "naive" ||
        ((plan.get "strategy").text == "tiled" && (plan.get "block").nat > 0 && (plan.get "block").nat ≤ n))
    formula := fun plan => s!"C[i,j] = fold(k=0..{n}-1, acc + A[i,k]*B[k,j]); strategy={(plan.get "strategy").text}; block={(plan.get "block").nat}"
    pseudocode := fun plan =>
      if (plan.get "strategy").text == "tiled" then
        s!"zero C; block={(plan.get "block").nat}\nfor ii,jj,kk in increasing block starts:\n  for i in ii tile; k in kk tile; j in jj tile:\n    C[i,j] = C[i,j] + A[i,k] * B[k,j]\nclip all tiles at n\n"
      else
        "for i,j: acc=0; for k increasing: acc=acc+A[i,k]*B[k,j]; C[i,j]=acc\n"
    transformations := [tileRule n]
  }

end MathKernel.TaskModel
