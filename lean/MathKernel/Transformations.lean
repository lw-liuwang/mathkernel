import MathKernel.Workflow

namespace MathKernel.Workflow

structure TransformationStep where
  rule : String
  arguments : Value

structure AppliedStep where
  step : TransformationStep
  before : Value
  after : Value

structure Derivation where
  plan : Value
  trace : List AppliedStep

structure DerivationFailure where
  index : Nat
  rule : String
  reason : String
  trace : List AppliedStep

def applyStep (model : Model) (plan : Value) (step : TransformationStep) : Except String Value :=
  match model.transformations.find? (fun rule => rule.name == step.rule) with
  | none => .error s!"Unknown rule: {step.rule}"
  | some rule => rule.apply plan step.arguments

theorem applyStep_sound (model : Model) (plan : Value) (step : TransformationStep)
    (result : Value) (h : applyStep model plan step = .ok result) :
    ∀ x, model.execute result x = model.execute plan x := by
  unfold applyStep at h
  split at h
  · contradiction
  · exact Transformation.sound _ plan step.arguments result h

def replay (model : Model) (plan : Value) (steps : List TransformationStep)
    (index : Nat := 1) : Except DerivationFailure Derivation :=
  match steps with
  | [] => .ok ⟨plan, []⟩
  | step :: rest =>
    match applyStep model plan step with
    | .error reason => .error ⟨index, step.rule, reason, []⟩
    | .ok next =>
      match replay model next rest (index + 1) with
      | .error failure => .error { failure with trace := ⟨step, plan, next⟩ :: failure.trace }
      | .ok result => .ok ⟨result.plan, ⟨step, plan, next⟩ :: result.trace⟩

theorem replay_sound (model : Model) (plan : Value) (steps : List TransformationStep)
    (index : Nat) (result : Derivation) (h : replay model plan steps index = .ok result) :
    ∀ x, model.execute result.plan x = model.execute plan x := by
  induction steps generalizing plan index result with
  | nil =>
    simp [replay] at h
    subst result
    intro x
    rfl
  | cons step rest ih =>
    cases ha : applyStep model plan step with
    | error reason => simp [replay, ha] at h
    | ok next =>
      cases hr : replay model next rest (index + 1) with
      | error reason => simp [replay, ha, hr] at h
      | ok tail =>
        simp [replay, ha, hr] at h
        subst result
        intro x
        exact (ih next (index + 1) tail hr x).trans (applyStep_sound model plan step next ha x)

theorem derivedCorrect (model : Model) (baseline : Value) (steps : List TransformationStep)
    (candidate : Value)
    (h : (replay model baseline steps).map (·.plan) = .ok candidate)
    (baselineCorrect : ∀ x, model.execute baseline x = model.specification x) :
    ∀ x, model.execute candidate x = model.specification x := by
  cases hr : replay model baseline steps with
  | error reason => simp [hr, Except.map] at h
  | ok result =>
    simp [hr, Except.map] at h
    subst candidate
    intro x
    exact (replay_sound model baseline steps 1 result hr x).trans (baselineCorrect x)

partial def Value.toJson : Value → Lean.Json
  | .null => .null
  | .bool value => Lean.toJson value
  | .int value => Lean.toJson value
  | .str value => Lean.toJson value
  | .array values => Lean.toJson (values.map Value.toJson)
  | .object fields => Lean.Json.mkObj (fields.map fun (key, value) => (key, value.toJson))

def validateRules (model : Model) : Except String Unit := do
  let mut names : List String := []
  for rule in model.transformations do
    if rule.name.trim.isEmpty then
      throw "Rule names must be nonempty"
    if names.contains rule.name then
      throw s!"Duplicate rule name: {rule.name}"
    names := rule.name :: names

def rulesJson (model : Model) : Lean.Json :=
  match validateRules model with
  | .error reason => Lean.Json.mkObj [("verification_status", Lean.toJson "invalid_rules"),
      ("diagnostic", Lean.toJson reason)]
  | .ok _ => Lean.Json.mkObj [("rules", Lean.toJson (model.transformations.map fun rule =>
      Lean.Json.mkObj [("name", Lean.toJson rule.name), ("description", Lean.toJson rule.description)]))]

def appliedStepJson (model : Model) (entry : AppliedStep) : Lean.Json :=
  Lean.Json.mkObj [("rule", Lean.toJson entry.step.rule), ("arguments", entry.step.arguments.toJson),
    ("before", entry.before.toJson), ("after", entry.after.toJson),
    ("before_formula", Lean.toJson (model.formula entry.before)),
    ("after_formula", Lean.toJson (model.formula entry.after))]

def derivationJson (model : Model) (baseline : Value) (steps : List TransformationStep) : Lean.Json :=
  match validateRules model with
  | .error _ => rulesJson model
  | .ok _ =>
    match replay model baseline steps with
    | .error failure => Lean.Json.mkObj [("verification_status", Lean.toJson "rule_failed"),
        ("diagnostic", Lean.toJson s!"Step {failure.index} ({failure.rule}): {failure.reason}"),
        ("failed_step", Lean.toJson failure.index),
        ("trace", Lean.toJson (failure.trace.map (appliedStepJson model)))]
    | .ok result => Lean.Json.mkObj [
        ("candidate_plan", result.plan.toJson),
        ("trace", Lean.toJson (result.trace.map (appliedStepJson model))),
        ("evaluation", Lean.Json.mkObj [("baseline", evaluationJson model baseline),
          ("candidate", evaluationJson model result.plan)])]

end MathKernel.Workflow
