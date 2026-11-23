import TaskInstance

namespace MathKernel.TaskProof
open TaskInstance

theorem baselineCorrect : ∀ x, model.execute baseline x = model.specification x := by
  intro x
  rfl

end MathKernel.TaskProof
