# 完成一次可验收的数学变换

用户提出计算需求和资源条件，agent 按本流程准备任务、提出候选、迭代验证并交付优化计算方案。任务可以包含新 kernel、已有 kernel，以及它们的合并或切分。候选生成策略由 agent 决定。

## 安装与接收任务

按 [README](../README.md) 获取仓库、准备 Lean 和绘图环境，然后用同一个 Python 运行：

```bash
python3 tools/mathkernel.py doctor
python3 tools/mathkernel.py task init /path/to/task
python3 tools/mathkernel.py task check /path/to/task
```

`doctor` 检查运行环境；`task check` 检查任务信息和确认状态。环境未准备好时可以继续整理需求，但评价、证明和绘图需要相应依赖。

收集数学规格、输入输出的形状与取值域、数值语义、输入条件、计算资源、基线执行方案、优化目标和迭代预算。规格包括数据初始和最终位置、允许的变换范围，以及会影响正确性或成本的约束。已有 kernel 代码可作为输入材料，但须先明确它要实现的数学计算。

在 `task.json` 中整理这些信息；格式见 [任务协议](../docs/tasks.md)。`check` 返回 `needs_information` 时，根据 `issues` 逐项询问用户，并解释该信息的用途。可以协助查询和整理，不能自行假设用户未提供的事实。

## 补充模型与用户确认

读取用户提供的实验定义。缺少数学定义、执行语义、成本规则或硬件假设时，说明需要补充的内容，并请求用户授权。授权前不替用户补全；获准后在 `supplements` 中记录补充内容、依据、授权人和授权范围。

每个实验使用任务目录中的 Lean 定义，接受任务与方案的结构化数据，提供数学规格、执行语义、资源计数、可行性和展示内容。不要以任意定理编译成功代替完整证明义务。具体接口见 [任务协议](../docs/tasks.md#接入新的计算模型)。

将整理后的规格、模型含义和关键假设、基线、目标、资源约束及预算展示给用户。用户确认后才能记录确认并开始优化：

```bash
python3 tools/mathkernel.py task confirm /path/to/task --by '<确认人>' --note '<用户实际确认内容>'
```

这个命令记录已经发生的确认，不代表用户授权本身。示例参数、测试中的确认记录和 agent 自行填写的文本都不能替代用户决策。补充授权和补充结果确认是两件事。

任务依据确认后保持固定。确需修改规格、模型、硬件、目标或预算时，说明变化并取得新确认；旧候选的证据不能用于新版本验收。

## 多轮候选与证明

候选文件包含 `plan`，以及可选的任务证明文件 `proof`。计划数据由模型解释，须表达数学变换及影响成本的执行组织。不要只交付一个脱离执行安排的公式。

```bash
python3 tools/mathkernel.py task evaluate /path/to/task /path/to/candidate.json
python3 tools/mathkernel.py task verify /path/to/task ITERATION_ID
```

`evaluate` 返回实际迭代 ID、成本、公式、伪代码和目标是否达到。它执行模型的评价程序；`not_run` 表示尚未证明。每次评价消耗一次候选预算，包括失败和超时。

新模型需要证明基线和候选都符合规格。可以在评价后补充或修订证明：

```bash
python3 tools/mathkernel.py task verify /path/to/task ITERATION_ID --proof /path/to/Proof.lean
```

每次验证保留新记录。Lean 还会检查资源可行、Python 报告与模型计数一致、目标改善成立及证明公理。查看返回的 `diagnostic` 和运行目录中的 `lean.log`；区分无改进、不可行、证明错误、超时和环境不可用，不把失败解释为数学上不存在改进。

根据诊断修改候选并再次评价，保持已验证的最好结果：

```bash
python3 tools/mathkernel.py task status /path/to/task
```

达到用户目标可提前结束。预算耗尽后停止生成新候选，可对已有候选执行最终验收。若没有合格候选，保留任务、尝试范围、诊断和停止原因；请用户决定是否调整任务或预算。

## 验收与交付

```bash
python3 tools/mathkernel.py task accept /path/to/task ITERATION_ID
python3 tools/mathkernel.py task export /path/to/task ITERATION_ID --output /path/to/new-bundle
python3 tools/mathkernel.py task accept /path/to/new-bundle
```

`accept` 重新评价与运行 Lean，检查当前规格和候选绑定、成本与展示内容，并生成 Roofline 和报告。`export` 先验收，再导出并在独立产出目录再次验收。默认停止原因为 `target_met`，也可以指定 `--stop-reason budget_exhausted` 或 `user_stopped`。

产出包包括结构化方案、公式与执行伪代码、Roofline PNG 与坐标数据、成本对比、确认后的任务与模型、证明材料、探索范围和重新验收说明。交付 `acceptance_status: accepted` 的目录，并说明适用条件和资源取舍。报告不声明未证明的最优性。

可以在本地或远端 CI 调用相同命令：成功退出为 0，未就绪、证明失败或验收拒绝为 1，输入错误为 2。只有通过 Lean 检查才能报告数学变换已验证；只有完整产出通过验收才能报告可交付。
