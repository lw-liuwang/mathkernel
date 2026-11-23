# 任务协议与验收

MathKernel 的任务目录连接用户需求、agent 的多轮变换和最终产出。CLI 输出 JSON，可供 agent 或 CI 解析。命令形式为 `python3 tools/mathkernel.py task ACTION DIRECTORY`；运行时的 Python 必须具备相关依赖。

## 任务输入

`task init DIRECTORY` 创建空模板。Agent 根据用户的计算需求准备任务信息、任务局部的 Lean 定义和证明，再运行 `check`。主分支不提供可选 kernel 模型或示例。

| 字段 | 内容 |
| --- | --- |
| `schema_version`、`name` | 当前协议版本为 1，以及任务名称 |
| `specification` | `description`、输入与输出列表、`semantics` 和 `conditions`；每个输入输出记录 `name`、`shape`、`domain` |
| `hardware` | 名称、峰值 FLOP/s、慢速存储边界带宽（字节/s）、快速存储字节数、每个数据字的字节数，字段沿用现有硬件格式 |
| `model` | `definition` 指向任务目录内的 Lean 定义文件 |
| `baseline` | 由模型解释的原始结构化计算方案 |
| `objective` | 最小化的 `metric` 和 `minimum_reduction` |
| `constraints` | 可选资源上限；没有附加限制时使用 `{}` |
| `budget` | 正整数 `max_iterations`、`max_seconds`，至少提供一项 |
| `supplements` | 补充内容及授权记录，没有补充时为 `[]` |

输入条件需要说明对数学或资源计数有影响的数据位置、别名、允许变换等前提。通用检查能指出缺少字段和明显冲突；agent 与用户仍需核对描述是否准确，不能从“字段齐全”推断规格正确。

`objective.metric` 支持 `estimated_seconds`、`flops`、`hbm_bytes`、`peak_fast_memory_bytes`。`minimum_reduction` 使用整数 `numerator`、`denominator`，满足 `0 ≤ numerator < denominator`；`0/1` 表示严格改善，`1/3` 表示至少减少三分之一，比较使用精确整数。`constraints` 支持 FLOP、搬运字节和快速存储峰值的正整数上限，基线和候选都须满足。模型还能定义任务特有的可行性条件。

每个补充记录 `scope`、`content`、`basis`、`authorized_by` 和 `authorization`，均为非空文本。用户先授权 agent 补充，再确认补充后的完整任务。授权记录的真实性由使用工作流的 agent 负责；本地文件记录决策，不提供用户身份认证。

`review.json` 保存确认人、实际确认内容及任务版本。版本绑定任务、模型定义和 MathKernel 的 Lean 模型来源。改变其中任何一项后需要重新确认和评价。任务可增加 `parameters` 等模型专用数据；数字使用整数，分数用分子分母对象表示。

## 接入新的计算模型

每个实验使用任务目录内的一个自包含 Lean 源文件，可导入固定版本 Mathlib 与 MathKernel。实验需要的 Mathlib 模块缓存由 agent 根据定义准备，例如在 `lean/` 中运行 `lake exe cache get MODULE`。文件声明：

```lean
MathKernel.TaskModel.model (task : MathKernel.Workflow.Value) : MathKernel.Workflow.Model
```

`task` 是确认后的完整任务数据。方案同样编码为 `Value`，支持空值、布尔、整数、字符串、数组和对象。模型必须提供：

- `Input`、`Output`、`specification`：输入输出类型与原始数学规格；输入条件应体现在类型或显式前提中。
- `execute`：结构化计算方案的数学含义，包括新算子、合并或切分后的计算关系。
- `resources`：按执行顺序给出的资源记录，每项含 FLOP、跨建模存储边界的字节数、快速存储峰值。
- `feasible`：模型特有的合法性检查。
- `formula`、`pseudocode`：从方案生成可读的数学表示和执行说明。
- `transformations`：可选的变换规则列表，默认 `[]`。规则接口和证明义务见下文。

本版公共 Roofline 工具对每项资源记录计算 `max(F/P, Q/B)`，然后求和；峰值存储取最大值。其他执行依赖、存储层级或资源约束可以在任务模型中表达，但报告的时间结论限于这个顺序 Roofline 解释。定义资源规则时须说明它们对应什么执行过程，不能只为得到改进填写更小数字。模型准确性与展示含义在用户确认时核对，Lean 检查确认模型内部的证明。

候选 JSON 包含 `plan` 对象及可选的 `proof` 相对路径。模型解释 `plan`，不限定 kernel 类型。证明可在评价后通过 `task verify ... --proof FILE` 提供。证明文件导入工具生成的 `TaskInstance`，在 `MathKernel.TaskProof` 下提供：

```lean
theorem baselineCorrect : ∀ x, model.execute baseline x = model.specification x := ...
theorem candidateCorrect : ∀ x, model.execute candidate x = model.specification x := ...
```

`MathKernel.TaskInstance` 提供绑定当前输入的 `task`、`model`、`baseline`、`candidate`、`hardware`、`goal`。工具生成完整的 `Workflow.Verified` 实例，额外检查基线和候选可行、报告计数匹配以及目标改进。任意 `True` 定理、`sorry`、额外公理或仅编译成功都不能替代这些义务。

公式和伪代码由同一模型解释器生成，验收会重新生成并核对。它们用于解释方案，不是单独经过验证的硬件代码。

## 可执行的变换链

任务可以在模型定义中提供 `Workflow.Transformation execute`，其中 `execute` 是该模型的执行语义：

```lean
structure Transformation {Input Output : Type} (execute : Value → Input → Output) where
  name : String
  description : String
  apply : Value → Value → Except String Value
  sound : ∀ plan arguments result, apply plan arguments = .ok result →
    ∀ x, execute result x = execute plan x
```

`apply` 依次接收当前方案和参数，返回新方案或不适用原因。规则负责解析参数、检查适用条件和处理局部变换位置；`description` 应说明参数格式与前提。应用函数须能在证明检查时由 Lean 归约，变换链的最终结果须为可序列化的非空方案对象。`sound` 证明每次成功应用均保持计算结果；输入条件通过模型的 `Input` 类型表达。规则不必证明成本下降，也不要求中间方案满足最终资源约束。

将规则填入模型的 `transformations` 列表。名称必须非空且唯一。规则和证明都位于任务自包含的模型源文件中，随模型版本一起确认；增加或修改规则需要重新确认。主分支不提供具体数学规则库。

```bash
python3 tools/mathkernel.py task rules /path/to/task
```

`rules` 返回规则名称、说明和任务版本；模型没有规则时返回空列表。它要求任务信息完整，可在用户确认前调用，不启动探索预算，也不认证规则证明。每条 Lean 命令受 `--timeout` 限制。

候选可以使用 `derivation` 代替 `plan`，两者互斥：

```json
{
  "derivation": [
    {"rule": "rule_name", "arguments": {}},
    {"rule": "another_rule", "arguments": {}}
  ],
  "proof": "BaselineProof.lean"
}
```

`derivation` 是非空列表，每步只有非空 `rule` 名称和 `arguments` 对象，数值沿用整数约定。`evaluate` 从已确认的基线开始顺序应用规则，并从模型生成最终方案、公式、成本和逐步记录。工具不自动搜索规则或参数。应用失败返回 `rule_failed`、从 1 开始的 `failed_step`、原因及此前成功步骤；重复或空规则名返回 `invalid_rules`。

变换链模式的证明文件只需提供 `MathKernel.TaskProof.baselineCorrect`，可在不同候选间复用；也可在评价后用 `verify --proof FILE` 提供。工具重放变换链，通过规则的 `sound` 和通用组合定理构造候选正确性证明。生成的 `TaskInstance.candidate` 来自 Lean 中的重放结果，保留规则产生的 `Value` 表示；保存的 `plan.json` 是它的 JSON 展示。验证会重新生成并核对展示方案及完整推导过程。

验证仍检查基线正确性、最终方案和基线的可行性、报告计数及目标改进。使用到的规则证明也纳入最终证书的公理检查；仅能执行规则不表示变换已经验证。

## 迭代与预算

`iterations/ID/` 保存确认后的输入快照、`plan.json`、评价结果、证明源文件与逐次验证日志。变换链另存 `derivation.json`，含提交的 `steps` 及执行生成的 `trace`；每个成功步骤记录规则、参数、输入输出方案和前后公式。每次 `evaluate` 预先记录一个尝试，再调用模型；整条变换链算一次候选评价，开始执行后的失败和超时也消耗预算。评价由 Lean 执行任务模型，不做数学正确性认证。

`max_iterations` 限制新候选评价次数；`max_seconds` 从首次评价开始按墙钟时间限制探索，包括两次调用间的时间。单次评价和搜索中的证明调用受剩余时间与 `--timeout` 共同限制。`--timeout` 默认为每条 Lean 命令 120 秒。最终 `accept` 和 `export` 使用独立的命令超时，允许在探索预算耗尽后完成已有方案的验收。

修订证明后可再次验证，历史验证不覆盖。`status` 返回当前任务版本的尝试数、时间预算状态与最佳已验证候选。这里的最佳只针对已验证候选，不声明全局最优。

## 验收与产出包

`accept DIRECTORY ID` 重新评价当前方案并运行完整 Lean 证明。变换链还会重新执行所有步骤。任务、模型、方案或推导记录与快照不符，成本或展示内容已变，目标未达到、证明失败或绘图不可用时，验收不会通过。

`export DIRECTORY ID --output NEW_DIRECTORY` 在验收后导出必要输入、选定候选、证明源文件、日志与结果，并再次验收。输出目录必须是任务目录以外的新目录。包内 `artifacts/ID/` 包含：

- `scheme.json`：结构化方案、前后公式与执行伪代码；变换链模式另含 `derivation` 的步骤和逐步记录。
- `costs.json`、`report.md`：资源变化、模型耗时、适用条件和结论。
- `roofline.png`、`roofline.json`：图与坐标数据。
- `exploration.json`：已尝试范围、预算状态与停止原因。

`bundle.json` 记录来源版本、选定候选及文件摘要；用于发现产出缺失或修改，不是数字签名。对包执行 `accept DIRECTORY` 会核对文件、重新评价和证明，并重新绘图比较。重新验收产生独立检查记录，不修改原始证明材料。需要同一版本 MathKernel、固定 Lean/Mathlib 与 `requirements-plot.txt` 的绘图环境。

Roofline 对零 FLOP 或零搬运量的点保留成本与耗时，省略无法在双对数坐标上表示的位置；右侧耗时比较仍显示完整方案。

## 状态与退出码

`check` 区分 `needs_information`、`invalid_task`、`needs_confirmation` 和 `ready`。`doctor` 另行检查环境。`init` 成功创建目录返回 0，即使模板还待补充。

评价结果的 `not_run` 表示尚未证明；`invalid_rules` 表示规则名称无效，`rule_failed` 表示某步无法应用。证明结果包含 `verified`、`proof_failed`、`timeout`、`unavailable`、`untrusted_proof`；最终验收另有 `acceptance_status`，只有 `accepted` 表示完整产出合格。发现保存的评价与当前模型不一致时返回 `stale_evaluation`。

成功为退出码 0；待补充、待确认、预算耗尽、证明未通过或验收拒绝为 1；输入错误为 2。远端 CI 可以直接调用这些命令，不需要另写一套验收逻辑。
