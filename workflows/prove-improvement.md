# 找到并证明一个改进方案

目标是在给定任务和硬件模型下，找到等价、可行且估计耗时严格低于基线的方案。候选由 agent 提出，工具执行评价与形式化检查。

## 输入与任务边界

读取任务 JSON，不修改其中的数学规格、基线和硬件参数。第一版覆盖三矩阵链、实数精确语义、单设备两级存储。候选只能改变结合顺序和统一的分块参数。

从项目根目录执行：

```bash
python3 tools/mathkernel.py inspect examples/matmul-chain/task.json
```

确认基线可行。若基线不满足任务约束，说明冲突并请求修订规格；比较对象需要先合法。

## 提出与评价候选

创建一个候选 JSON，例如：

```json
{"order": "right", "tile": {"m": 64, "n": 64, "k": 64}}
```

```bash
python3 tools/mathkernel.py evaluate examples/matmul-chain/task.json examples/matmul-chain/candidate.json
```

结合顺序影响 GEMM 形状、计算量和中间结果；分块影响数据复用与容量。根据每个 GEMM 的瓶颈及模型耗时选择候选。评价结果中的 `not_run` 表示尚未进行 Lean 验证。

需要查看 Roofline 位置时，使用绘图环境运行：

```bash
.venv/bin/python tools/mathkernel.py roofline examples/matmul-chain/task.json examples/matmul-chain/candidate.json --output runs/roofline
```

工具导出 PNG 图与坐标数据，标出每次 GEMM 和完整方案，同时对照模型耗时。绘图环境的安装命令见 [README](../README.md#roofline-图)。

## 证明与诊断

```bash
python3 tools/mathkernel.py verify examples/matmul-chain/task.json examples/matmul-chain/candidate.json
```

`verify` 生成具体实例，复用 Lean 中的实数矩阵结合律与成本解释器，检查：

1. 候选和基线的输出对所有合法实数矩阵相同。
2. 两个方案均满足分块和快速存储容量约束。
3. 候选的有理数形式估计耗时严格低于基线。
4. 报告中的计算量、搬运量、峰值占用和时间计数与 Lean 解释器一致。

退出码 0 表示证明通过；1 表示验证未通过，具体状态和诊断见结果与日志；2 表示输入错误。

## 交付结果

对验证输出给出的实际运行目录执行：

```bash
python3 tools/mathkernel.py report runs/RUN_ID/result.json
```

报告命令只呈现已保存的结果，不重新验证。需要重现证明时，使用运行目录中的 `task.json` 和 `candidate.json` 再次执行 `verify`。

交付具体候选、适用条件、资源和模型耗时变化，以及运行目录。

如果预算内没有找到通过验证的候选，交付已探索范围和未解决项。扩展任务类型时，同步补充 Lean 语义和成本规则。
