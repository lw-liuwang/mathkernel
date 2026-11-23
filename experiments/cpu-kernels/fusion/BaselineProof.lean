import TaskInstance

set_option maxRecDepth 8192

namespace MathKernel.TaskProof
open TaskInstance

theorem baselineCorrect : ∀ x, model.execute baseline x = model.specification x := by
  intro x
  exact TaskModel.execute_correct (((task.get "parameters").get "n").nat) baseline x

end MathKernel.TaskProof
