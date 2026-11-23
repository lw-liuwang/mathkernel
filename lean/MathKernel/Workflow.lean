import Lean

namespace MathKernel.Workflow

structure Hardware where
  peakFlops : Nat
  bandwidth : Nat
  fastBytes : Nat
  elementBytes : Nat

structure Resources where
  flops : Nat
  hbmBytes : Nat
  peakBytes : Nat
  deriving Repr, DecidableEq

-- Models interpret the exact task and plan snapshots supplied by the workflow.
inductive Value where
  | null
  | bool (value : Bool)
  | int (value : Int)
  | str (value : String)
  | array (values : List Value)
  | object (fields : List (String × Value))
  deriving Repr

def Value.get (value : Value) (key : String) : Value :=
  match value with
  | .object fields => (fields.find? (fun field => field.1 == key)).map Prod.snd |>.getD .null
  | _ => .null

def Value.nat (value : Value) : Nat :=
  match value with
  | .int n => n.toNat
  | _ => 0

def Value.text (value : Value) : String :=
  match value with
  | .str s => s
  | _ => ""

structure Transformation {Input Output : Type} (execute : Value → Input → Output) where
  name : String
  description : String
  apply : Value → Value → Except String Value
  sound : ∀ plan arguments result, apply plan arguments = .ok result →
    ∀ x, execute result x = execute plan x

structure Model where
  Input : Type
  Output : Type
  specification : Input → Output
  execute : Value → Input → Output
  resources : Value → List Resources
  feasible : Value → Bool
  formula : Value → String
  pseudocode : Value → String
  transformations : List (Transformation execute) := []

inductive Metric where
  | time | flops | bytes | storage
  deriving Repr

structure Goal where
  metric : Metric
  reductionNumerator : Nat
  reductionDenominator : Nat
  maxFlops : Option Nat := none
  maxBytes : Option Nat := none
  maxStorage : Option Nat := none

def total (operations : List Resources) : Resources :=
  operations.foldl (fun acc op =>
    ⟨acc.flops + op.flops, acc.hbmBytes + op.hbmBytes, max acc.peakBytes op.peakBytes⟩) ⟨0, 0, 0⟩

def ticks (hardware : Hardware) (operations : List Resources) : Nat :=
  (operations.map (fun op => max (op.flops * hardware.bandwidth)
    (op.hbmBytes * hardware.peakFlops))).foldl (· + ·) 0

def metric (hardware : Hardware) (goal : Goal) (operations : List Resources) : Nat :=
  match goal.metric with
  | .time => ticks hardware operations
  | .flops => (total operations).flops
  | .bytes => (total operations).hbmBytes
  | .storage => (total operations).peakBytes

def within (value : Nat) (limit : Option Nat) : Bool :=
  match limit with
  | none => true
  | some n => value ≤ n

def feasible (model : Model) (plan : Value) (hardware : Hardware) (goal : Goal) : Bool :=
  let cost := total (model.resources plan)
  model.feasible plan && !(model.resources plan).isEmpty &&
    hardware.peakFlops > 0 && hardware.bandwidth > 0 && hardware.elementBytes > 0 &&
    cost.peakBytes ≤ hardware.fastBytes && within cost.flops goal.maxFlops &&
    within cost.hbmBytes goal.maxBytes && within cost.peakBytes goal.maxStorage

def improves (hardware : Hardware) (goal : Goal) (baseline candidate : List Resources) : Bool :=
  let before := metric hardware goal baseline
  let after := metric hardware goal candidate
  goal.reductionDenominator > 0 && goal.reductionNumerator < goal.reductionDenominator &&
    after < before && after * goal.reductionDenominator ≤
      before * (goal.reductionDenominator - goal.reductionNumerator)

structure Verified (model : Model) (baseline candidate : Value) (hardware : Hardware)
    (goal : Goal) (baselineReport candidateReport : List Resources) : Prop where
  baselineCorrect : ∀ x, model.execute baseline x = model.specification x
  candidateCorrect : ∀ x, model.execute candidate x = model.specification x
  baselineFeasible : feasible model baseline hardware goal = true
  candidateFeasible : feasible model candidate hardware goal = true
  baselineCounts : model.resources baseline = baselineReport
  candidateCounts : model.resources candidate = candidateReport
  improvement : improves hardware goal baselineReport candidateReport = true

def operationJson (r : Resources) : Lean.Json :=
  Lean.Json.mkObj [("flops", Lean.toJson r.flops), ("hbm_bytes", Lean.toJson r.hbmBytes),
    ("peak_fast_memory_bytes", Lean.toJson r.peakBytes)]

def evaluationJson (model : Model) (plan : Value) : Lean.Json :=
  Lean.Json.mkObj [("operations", Lean.toJson ((model.resources plan).map operationJson)),
    ("feasible", Lean.toJson (model.feasible plan)), ("formula", Lean.toJson (model.formula plan)),
    ("pseudocode", Lean.toJson (model.pseudocode plan))]

end MathKernel.Workflow
