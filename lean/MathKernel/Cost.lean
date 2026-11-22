import MathKernel.Semantics

namespace MathKernel

structure Resources where
  flops : Nat := 0
  hbmBytes : Nat := 0
  peakBytes : Nat := 0
  deriving Repr

-- Cost semantics for an abstract blocked schedule. GEMM tile events count an
-- FMA as two operations and exclude loop, address, and initialization overhead.
inductive Schedule where
  | event (flops bytes : Nat)
  | seq (first second : Schedule)
  | repeat (count : Nat) (body : Schedule)
  | reserve (bytes : Nat) (body : Schedule)

def Schedule.cost : Schedule → Resources
  | .event f q => ⟨f, q, 0⟩
  | .seq a b =>
      let x := a.cost
      let y := b.cost
      ⟨x.flops + y.flops, x.hbmBytes + y.hbmBytes, max x.peakBytes y.peakBytes⟩
  | .repeat n body =>
      let x := body.cost
      ⟨n * x.flops, n * x.hbmBytes, if n = 0 then 0 else x.peakBytes⟩
  | .reserve bytes body =>
      let x := body.cost
      ⟨x.flops, x.hbmBytes, bytes + x.peakBytes⟩

structure Gemm where
  m : Nat
  k : Nat
  n : Nat
  deriving Repr

def gemms (t : Task) (p : Plan) : List Gemm :=
  match p.order with
  | .left => [⟨t.m, t.k, t.n⟩, ⟨t.m, t.n, t.p⟩]
  | .right => [⟨t.k, t.n, t.p⟩, ⟨t.m, t.k, t.p⟩]

def workingBytes (h : Hardware) (b : Tile) : Nat :=
  h.elementBytes * (b.m * b.k + b.k * b.n + b.m * b.n)

def gemmSchedule (h : Hardware) (b : Tile) (g : Gemm) : Schedule :=
  .reserve (workingBytes h b)
    (.repeat (g.m / b.m)
      (.repeat (g.n / b.n)
        (.seq
          (.repeat (g.k / b.k)
            (.event (2 * b.m * b.n * b.k)
              (h.elementBytes * (b.m * b.k + b.k * b.n))))
          (.event 0 (h.elementBytes * b.m * b.n)))))

def legalGemm (h : Hardware) (b : Tile) (g : Gemm) : Bool :=
  b.m > 0 && b.n > 0 && b.k > 0 &&
    g.m > 0 && g.n > 0 && g.k > 0 &&
    g.m % b.m == 0 && g.n % b.n == 0 && g.k % b.k == 0 &&
    workingBytes h b ≤ h.fastBytes

def validTask (t : Task) : Bool :=
  t.m > 0 && t.k > 0 && t.n > 0 && t.p > 0 &&
    t.hardware.peakFlops > 0 && t.hardware.bandwidth > 0 &&
    t.hardware.fastBytes > 0 && t.hardware.elementBytes > 0

def feasible (t : Task) (p : Plan) : Bool :=
  validTask t && (gemms t p).all (legalGemm t.hardware p.tile)

def gemmTicks (h : Hardware) (b : Tile) (g : Gemm) : Nat :=
  let r := (gemmSchedule h b g).cost
  max (r.flops * h.bandwidth) (r.hbmBytes * h.peakFlops)

-- All GEMMs share the positive denominator peakFlops * bandwidth. Summation
-- models sequential GEMMs, with ideal overlap only inside each GEMM.
def timeTicks (t : Task) (p : Plan) : Nat :=
  ((gemms t p).map (gemmTicks t.hardware p.tile)).sum

def totalResources (t : Task) (p : Plan) : Resources :=
  let costs := (gemms t p).map (fun g => (gemmSchedule t.hardware p.tile g).cost)
  ⟨(costs.map Resources.flops).sum,
    (costs.map Resources.hbmBytes).sum,
    costs.foldl (fun peak r => max peak r.peakBytes) 0⟩

def estimatedSeconds (t : Task) (p : Plan) : ℚ :=
  (timeTicks t p : ℚ) /
    ((t.hardware.peakFlops * t.hardware.bandwidth : Nat) : ℚ)

theorem lower_time_of_ticks (t : Task) (baseline candidate : Plan)
    (positiveRate : 0 < t.hardware.peakFlops * t.hardware.bandwidth)
    (lowerTicks : timeTicks t candidate < timeTicks t baseline) :
    estimatedSeconds t candidate < estimatedSeconds t baseline := by
  unfold estimatedSeconds
  have positiveDenominator :
      (0 : ℚ) < ((t.hardware.peakFlops * t.hardware.bandwidth : Nat) : ℚ) :=
    Nat.cast_pos.mpr positiveRate
  exact (div_lt_div_iff_of_pos_right positiveDenominator).mpr (Nat.cast_lt.mpr lowerTicks)

end MathKernel
