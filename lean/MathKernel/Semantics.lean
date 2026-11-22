import Mathlib.Data.Matrix.Mul
import Mathlib.Data.Real.Basic

namespace MathKernel

inductive Order where
  | left
  | right
  deriving Repr, DecidableEq

structure Tile where
  m : Nat
  n : Nat
  k : Nat
  deriving Repr

structure Plan where
  order : Order
  tile : Tile
  deriving Repr

structure Hardware where
  peakFlops : Nat
  bandwidth : Nat
  fastBytes : Nat
  elementBytes : Nat
  deriving Repr

structure Task where
  m : Nat
  k : Nat
  n : Nat
  p : Nat
  hardware : Hardware
  deriving Repr

-- A GEMM primitive denotes exact real matrix multiplication. Tiles select its
-- abstract schedule and cost.
def denote (t : Task) (plan : Plan)
    (a : Matrix (Fin t.m) (Fin t.k) ℝ)
    (b : Matrix (Fin t.k) (Fin t.n) ℝ)
    (c : Matrix (Fin t.n) (Fin t.p) ℝ) : Matrix (Fin t.m) (Fin t.p) ℝ :=
  match plan.order with
  | .left => (a * b) * c
  | .right => a * (b * c)

def Equivalent (t : Task) (baseline candidate : Plan) : Prop :=
  ∀ a b c, denote t candidate a b c = denote t baseline a b c

theorem plans_equivalent (t : Task) (baseline candidate : Plan) :
    Equivalent t baseline candidate := by
  intro a b c
  cases hb : baseline.order <;> cases hc : candidate.order <;>
    simp [denote, hb, hc, Matrix.mul_assoc]

end MathKernel
